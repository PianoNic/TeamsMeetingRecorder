"""Microphone playback: path safety, the ffmpeg|pacat pipeline, and the API.

No PulseAudio, ffmpeg or browser is involved - every subprocess is faked, so
this runs anywhere. What it pins down is the wiring: which argv gets built, what
the audio graph looks like, and what each endpoint answers.

Run: python -m pytest tests/   or   python tests/test_mic_playback.py
"""

import asyncio
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app import audio_out
from app.audio_out import (
    IngestClosed,
    MediaPathRejected,
    MicrophonePlayer,
    PlaybackBusy,
    PlaybackUnavailable,
    resolve_media_path,
)
from app.config import settings
from app.models import BotStatus


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakePipe:
    """Stands in for a subprocess stdin/stdout pipe."""

    def __init__(self):
        self.written = b""
        self.closed = False
        self.broken = False

    def write(self, data):
        if self.closed or self.broken:
            raise BrokenPipeError("pipe is closed")
        self.written += data
        return len(data)

    def read(self):
        return b""

    def close(self):
        self.closed = True


class FakeProc:
    """A subprocess that stays alive until terminated, recording its argv.

    wait() blocks like the real thing. A fake that returned immediately would
    let the watcher thread reap every playback the instant it started, and the
    tests would pass against a player that never actually kept anything alive.
    """

    def __init__(self, cmd, stdin=None, stdout=None, stderr=None):
        self.cmd = cmd
        self.stdin = FakePipe() if stdin is subprocess.PIPE else None
        self.stdout = FakePipe() if stdout is subprocess.PIPE else None
        self.stderr = FakePipe() if stderr is subprocess.PIPE else None
        self.stdout_arg = stdout
        self.terminated = False
        self.killed = False
        self._returncode = None
        self._done = threading.Event()

    def poll(self):
        return self._returncode

    def wait(self, timeout=None):
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        return self._returncode

    def terminate(self):
        self.terminated = True
        self.exit(0)

    def kill(self):
        self.killed = True
        self.exit(-9)

    def exit(self, code=0):
        """Simulate the process ending."""
        if self._returncode is None:
            self._returncode = code
        self._done.set()


class Spawner:
    """Collects every process a test spawns, newest last."""

    def __init__(self, fail_on=None):
        self.procs = []
        self.fail_on = fail_on

    def __call__(self, cmd, **kwargs):
        if self.fail_on and cmd[0] == self.fail_on:
            raise FileNotFoundError(cmd[0])
        proc = FakeProc(cmd, **kwargs)
        self.procs.append(proc)
        return proc

    def of(self, program):
        return [p for p in self.procs if p.cmd[0] == program]


@pytest.fixture
def spawner(monkeypatch):
    s = Spawner()
    monkeypatch.setattr(audio_out.subprocess, "Popen", s)
    return s


@pytest.fixture
def player(spawner):
    p = MicrophonePlayer("abcdef12-0000-0000-0000-000000000000", "teams_mic_abcdef12")
    yield p
    p.close()


def _settle():
    """Wait for the watcher threads to finish reaping."""
    for _ in range(200):
        if not any(t.name.startswith("mic-watch") and t.is_alive()
                   for t in threading.enumerate()):
            return
        time.sleep(0.01)
    raise AssertionError("a mic watcher thread never finished")


# --------------------------------------------------------------------------
# Media path containment
# --------------------------------------------------------------------------


@pytest.fixture
def media(tmp_path, monkeypatch):
    root = tmp_path / "media"
    (root / "sub").mkdir(parents=True)
    (root / "song.mp3").write_bytes(b"ID3fake")
    (root / "sub" / "nested.wav").write_bytes(b"RIFFfake")
    (tmp_path / "secret.txt").write_text("not yours")
    monkeypatch.setattr(settings, "media_dir", str(root))
    return root


def test_media_path_accepts_files_in_the_tree(media):
    assert resolve_media_path("song.mp3") == (media / "song.mp3").resolve()
    assert resolve_media_path("sub/nested.wav") == (media / "sub" / "nested.wav").resolve()


def test_media_path_rejects_traversal(media):
    with pytest.raises(MediaPathRejected):
        resolve_media_path("../secret.txt")


def test_media_path_rejects_absolute_path_outside(media):
    outside = str((media.parent / "secret.txt").resolve())
    with pytest.raises(MediaPathRejected):
        resolve_media_path(outside)


def test_media_path_rejects_directories_and_missing_files(media):
    with pytest.raises(MediaPathRejected):
        resolve_media_path("sub")
    with pytest.raises(MediaPathRejected):
        resolve_media_path("nope.mp3")


def test_media_path_rejects_symlink_escape(media, tmp_path):
    link = media / "escape.mp3"
    try:
        link.symlink_to(tmp_path / "secret.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted in this environment")
    with pytest.raises(MediaPathRejected):
        resolve_media_path("escape.mp3")


# --------------------------------------------------------------------------
# The ffmpeg | pacat pipeline
# --------------------------------------------------------------------------


def test_play_file_builds_the_pipeline(player, spawner, media):
    player.play_file(media / "song.mp3")

    pacat = spawner.of("pacat")[0].cmd
    assert "--device=teams_mic_abcdef12" in pacat
    assert "--format=s16le" in pacat

    ffmpeg = spawner.of("ffmpeg")[0].cmd
    assert "-nostdin" in ffmpeg          # a file never reads stdin
    assert "-re" in ffmpeg               # decode at realtime, not as fast as possible
    assert "-stream_loop" not in ffmpeg  # not asked to loop
    assert ffmpeg[-3:] == ["-f", "s16le", "pipe:1"]
    assert player.is_playing()


def test_ffmpeg_writes_into_pacat_and_the_parent_lets_go(player, spawner, media):
    player.play_file(media / "song.mp3")
    pacat = spawner.of("pacat")[0]
    ffmpeg = spawner.of("ffmpeg")[0]

    # ffmpeg's stdout IS pacat's stdin, and the parent's copy is closed so pacat
    # sees EOF when ffmpeg exits instead of hanging on to the sink.
    assert ffmpeg.stdout_arg is pacat.stdin
    assert pacat.stdin.closed


def test_loop_and_volume_reach_ffmpeg(player, spawner, media):
    player.play_file(media / "song.mp3", loop=True, volume=2.5)
    ffmpeg = spawner.of("ffmpeg")[0].cmd

    assert ffmpeg[ffmpeg.index("-stream_loop") + 1] == "-1"
    # -stream_loop is an input option: after -i it would be ignored.
    assert ffmpeg.index("-stream_loop") < ffmpeg.index("-i")
    assert ffmpeg[ffmpeg.index("-filter:a") + 1] == "volume=2.5"


def test_default_volume_adds_no_filter(player, spawner, media):
    player.play_file(media / "song.mp3")
    assert "-filter:a" not in spawner.of("ffmpeg")[0].cmd


def test_second_playback_is_refused_while_one_is_running(player, spawner, media):
    player.play_file(media / "song.mp3")
    with pytest.raises(PlaybackBusy):
        player.play_file(media / "sub" / "nested.wav")
    assert len(spawner.of("ffmpeg")) == 1


def test_stop_terminates_both_processes(player, spawner, media):
    player.play_file(media / "song.mp3")
    assert player.stop() is True

    assert spawner.of("ffmpeg")[0].terminated
    assert spawner.of("pacat")[0].terminated
    assert player.is_playing() is False
    assert player.stop() is False  # nothing left to stop


def test_missing_ffmpeg_is_reported_and_leaves_no_stray_pacat(monkeypatch, media):
    spawner = Spawner(fail_on="ffmpeg")
    monkeypatch.setattr(audio_out.subprocess, "Popen", spawner)
    player = MicrophonePlayer("sess", "teams_mic_sess")

    with pytest.raises(PlaybackUnavailable):
        player.play_file(media / "song.mp3")

    assert spawner.of("pacat")[0].killed
    assert player.is_playing() is False


def test_status_reports_what_is_playing(player, spawner, media):
    assert player.status()["playing"] is False

    player.play_file(media / "song.mp3", loop=True)
    state = player.status()
    assert state["playing"] is True
    assert state["kind"] == "file"
    assert state["source"] == "song.mp3"
    assert state["loop"] is True
    assert state["stream_open"] is False


def test_playback_after_close_is_refused(player, media):
    player.close()
    with pytest.raises(PlaybackUnavailable):
        player.play_file(media / "song.mp3")


# --------------------------------------------------------------------------
# Ingest streaming
# --------------------------------------------------------------------------


def test_open_stream_reads_stdin_and_skips_realtime_pacing(player, spawner):
    player.open_stream()
    ffmpeg = spawner.of("ffmpeg")[0].cmd

    assert "-i" in ffmpeg and ffmpeg[ffmpeg.index("-i") + 1] == "pipe:0"
    assert "-nostdin" not in ffmpeg  # it would fight -i pipe:0
    # The pusher already sends at realtime; -re on top of that would drift.
    assert "-re" not in ffmpeg


def test_open_stream_passes_an_explicit_input_format(player, spawner):
    player.open_stream(input_format="s16le")
    ffmpeg = spawner.of("ffmpeg")[0].cmd
    # -f before -i is the input format; the trailing one is the output format.
    assert ffmpeg.index("-f") < ffmpeg.index("-i")
    assert ffmpeg[ffmpeg.index("-f") + 1] == "s16le"


def test_token_only_matches_itself(player):
    token = player.open_stream()
    assert player.token_matches(token)
    assert not player.token_matches(token[:-1] + "x")
    assert not player.token_matches("")


def test_fed_bytes_reach_ffmpeg_stdin(player, spawner):
    player.open_stream()
    asyncio.run(player.feed(b"\x00\x01\x02"))
    assert spawner.of("ffmpeg")[0].stdin.written == b"\x00\x01\x02"
    assert player.status()["stream_connected"] is True


def test_feed_without_an_open_stream_is_refused(player):
    with pytest.raises(IngestClosed):
        asyncio.run(player.feed(b"data"))


def test_feed_into_a_file_playback_is_refused(player, media):
    player.play_file(media / "song.mp3")
    with pytest.raises(IngestClosed):
        asyncio.run(player.feed(b"data"))


def test_feed_after_the_decoder_dies_is_refused(player, spawner):
    player.open_stream()
    spawner.of("ffmpeg")[0].exit(1)
    with pytest.raises(IngestClosed):
        asyncio.run(player.feed(b"data"))


def test_feed_survives_a_broken_pipe_as_ingest_closed(player, spawner):
    player.open_stream()
    spawner.of("ffmpeg")[0].stdin.broken = True
    with pytest.raises(IngestClosed):
        asyncio.run(player.feed(b"data"))


def test_close_stream_retires_the_token_and_stops_the_pipeline(player, spawner):
    token = player.open_stream()
    assert player.close_stream() is True

    assert not player.token_matches(token)
    assert spawner.of("ffmpeg")[0].terminated
    assert player.status()["stream_open"] is False
    assert player.close_stream() is False


def test_stop_on_a_stream_closes_its_stdin_so_ffmpeg_sees_eof(player, spawner):
    player.open_stream()
    player.stop()
    assert spawner.of("ffmpeg")[0].stdin.closed


def test_close_stops_everything(player, spawner, media):
    player.play_file(media / "song.mp3")
    player.close()
    assert spawner.of("ffmpeg")[0].terminated
    assert player.status()["playing"] is False


# --------------------------------------------------------------------------
# Ending on its own
# --------------------------------------------------------------------------


def test_a_track_that_ends_clears_the_player(player, spawner, media):
    player.play_file(media / "song.mp3")
    spawner.of("ffmpeg")[0].exit(0)   # the track ran out
    spawner.of("pacat")[0].exit(0)
    _settle()

    assert player.is_playing() is False
    assert player.status()["source"] is None
    # And the player is reusable rather than stuck "busy" forever.
    player.play_file(media / "sub" / "nested.wav")
    assert player.is_playing() is True


def test_a_dead_ingest_decoder_retires_its_token(player, spawner):
    token = player.open_stream()
    spawner.of("ffmpeg")[0].exit(1)
    spawner.of("pacat")[0].exit(0)
    _settle()

    # The URL must stop working, rather than accept bytes into a dead pipe.
    assert not player.token_matches(token)
    assert player.status()["stream_open"] is False


def test_an_upload_is_deleted_once_it_has_been_played(player, spawner, media):
    upload = media / "uploads" / "tmp.mp3"
    upload.parent.mkdir(parents=True, exist_ok=True)
    upload.write_bytes(b"ID3fake")

    player.play_file(upload, temp_file=upload)
    spawner.of("ffmpeg")[0].exit(0)
    spawner.of("pacat")[0].exit(0)
    _settle()

    assert not upload.exists()


def test_an_upload_is_deleted_even_when_playback_is_cut_short(player, spawner, media):
    upload = media / "uploads" / "tmp.mp3"
    upload.parent.mkdir(parents=True, exist_ok=True)
    upload.write_bytes(b"ID3fake")

    player.play_file(upload, temp_file=upload)
    player.stop()
    _settle()

    assert not upload.exists()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
