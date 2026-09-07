"""Playing audio out through the bot's virtual microphone.

Every session owns a second null sink (the "mic sink"). Chromium's PULSE_SOURCE
points at that sink's monitor, so anything written into the sink is what the
meeting hears from the bot. Nothing playing means the monitor emits silence,
which is exactly what a connected-but-quiet microphone should sound like.

Audio reaches the sink through `ffmpeg | pacat`: ffmpeg decodes whatever it is
handed (a file, or a live stream on stdin) down to raw s16le, and pacat writes
those samples into the named sink. Decoding in ffmpeg rather than pacat is what
lets the ingest endpoint accept mp3/ogg/whatever without being told in advance.
"""

import asyncio
import logging
import secrets
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from app.config import DEFAULT_SAMPLE_RATE, DEFAULT_CHANNELS, settings

logger = logging.getLogger(__name__)


class MediaPathRejected(ValueError):
    """A requested path is outside the media directory, or is not a file."""


def media_root() -> Path:
    """The one directory files may be played from."""
    return Path(settings.media_dir).resolve()


def resolve_media_path(relative: str) -> Path:
    """Resolve a caller-supplied path inside the media directory.

    The API can run unauthenticated, so this is the boundary that keeps "play
    this file" from becoming "read any file on the container out loud". Symlinks
    are resolved before the containment check, so one pointing out of the tree
    is rejected rather than followed.
    """
    root = media_root()
    candidate = (root / relative).resolve()

    if candidate != root and root not in candidate.parents:
        raise MediaPathRejected(f"Path is outside the media directory: {relative}")
    if not candidate.is_file():
        raise MediaPathRejected(f"No such file in the media directory: {relative}")
    return candidate


class PlaybackKind(str, Enum):
    """What is currently feeding the microphone."""
    FILE = "file"
    STREAM = "stream"


class PlaybackBusy(RuntimeError):
    """Something is already playing through the microphone."""


class PlaybackUnavailable(RuntimeError):
    """Microphone playback is not available for this session."""


class IngestClosed(RuntimeError):
    """The ingest stream is not open, or the decoder behind it has exited."""


@dataclass
class _Playback:
    """One decode-and-play pipeline, alive until ffmpeg exits."""
    kind: PlaybackKind
    label: str
    ffmpeg: subprocess.Popen
    pacat: subprocess.Popen
    started_at: datetime
    loop: bool = False
    # Deleted once the pipeline ends. Set for uploads, which live only as long
    # as the playback that consumes them.
    temp_file: Optional[Path] = None
    # Set the moment stop() is called, so the watcher can tell a deliberate
    # stop from a track reaching its own end.
    stopped: bool = False


class MicrophonePlayer:
    """Owns one session's mic sink and whatever is playing into it."""

    # How long to wait for a terminated pipeline to actually go away before
    # killing it. ffmpeg and pacat both exit promptly on SIGTERM; this is only a
    # backstop so stop() can never hang a request.
    TERMINATE_TIMEOUT_S = 3

    def __init__(self, session_id: str, sink_name: str):
        self.session_id = session_id
        self.sink_name = sink_name
        self.source_name = f"{sink_name}.monitor"

        self._lock = threading.Lock()
        self._current: Optional[_Playback] = None
        self._ingest_token: Optional[str] = None
        self._ingest_connected = False
        self._closed = False

    # ------------------------------------------------------------------ state

    @staticmethod
    def _is_alive(playback: Optional[_Playback]) -> bool:
        return playback is not None and playback.ffmpeg.poll() is None

    def is_playing(self) -> bool:
        """Is a pipeline currently alive?"""
        with self._lock:
            return self._is_alive(self._current)

    def status(self) -> dict:
        """A snapshot of what the microphone is doing, for the API."""
        with self._lock:
            current = self._current if self._is_alive(self._current) else None
            return {
                "playing": current is not None,
                "kind": current.kind.value if current else None,
                "source": current.label if current else None,
                "loop": current.loop if current else False,
                "playback_started_at": current.started_at if current else None,
                "stream_open": self._ingest_token is not None,
                "stream_connected": self._ingest_connected,
            }

    # --------------------------------------------------------------- playback

    def play_file(self, path: Path, loop: bool = False, volume: float = 1.0,
                  temp_file: Optional[Path] = None) -> None:
        """Play an audio file into the microphone.

        Raises PlaybackBusy when something is already playing: two sources into
        one sink mix into an unintelligible mess, so the caller has to stop()
        first and mean it.
        """
        args = ["-nostdin"]
        if loop:
            # Before -i, so it applies to the input rather than the output.
            args += ["-stream_loop", "-1"]
        # Decode no faster than realtime. pacat's blocking writes already pace
        # the pipeline, but -re keeps ffmpeg from buffering a chunk of the file
        # ahead of the sink, which would delay stop() by that much.
        args += ["-re", "-i", str(path)]

        self._spawn(
            kind=PlaybackKind.FILE,
            label=path.name,
            input_args=args,
            stdin=subprocess.DEVNULL,
            volume=volume,
            loop=loop,
            temp_file=temp_file,
        )

    def open_stream(self, input_format: Optional[str] = None, volume: float = 1.0) -> str:
        """Open an ingest pipeline and return the token that addresses it.

        The decoder starts immediately and blocks on an empty stdin, so the URL
        handed back is live before the pushing application connects to it.
        """
        args: list[str] = []
        if input_format:
            # Only needed for headerless input (raw PCM); container formats are
            # sniffed from the bytes themselves.
            args += ["-f", input_format]
        args += ["-i", "pipe:0"]

        token = secrets.token_urlsafe(32)
        self._spawn(
            kind=PlaybackKind.STREAM,
            label="ingest",
            input_args=args,
            stdin=subprocess.PIPE,
            volume=volume,
            loop=False,
        )
        with self._lock:
            self._ingest_token = token
            self._ingest_connected = False
        logger.info(f"[{self.session_id}] Ingest stream opened")
        return token

    def token_matches(self, token: str) -> bool:
        """Constant-time check of an ingest token."""
        with self._lock:
            expected = self._ingest_token
        return bool(expected) and secrets.compare_digest(expected, token)

    async def feed(self, chunk: bytes) -> None:
        """Push encoded audio into the open ingest pipeline.

        The write runs off the event loop: when the sink is full ffmpeg stops
        reading, and that backpressure should reach the HTTP client pushing the
        audio rather than stall the whole API.
        """
        with self._lock:
            playback = self._current
            if playback is None or playback.kind is not PlaybackKind.STREAM:
                raise IngestClosed("No ingest stream is open")
            if playback.ffmpeg.poll() is not None or playback.ffmpeg.stdin is None:
                raise IngestClosed("The ingest decoder has exited")
            self._ingest_connected = True
            stdin = playback.ffmpeg.stdin

        try:
            await asyncio.to_thread(stdin.write, chunk)
        except (BrokenPipeError, ValueError, OSError) as e:
            raise IngestClosed(f"Ingest pipeline closed: {e}")

    def close_stream(self) -> bool:
        """Close the ingest pipeline. Returns whether one was open."""
        with self._lock:
            was_open = self._ingest_token is not None
            self._ingest_token = None
            self._ingest_connected = False
        if was_open:
            self.stop()
            logger.info(f"[{self.session_id}] Ingest stream closed")
        return was_open

    def stop(self) -> bool:
        """Stop whatever is playing. Returns whether anything was."""
        with self._lock:
            playback = self._current
            if playback is None:
                return False
            playback.stopped = True
            self._current = None

        was_alive = playback.ffmpeg.poll() is None
        self._terminate(playback)
        return was_alive

    def close(self) -> None:
        """Tear down for good; the session is ending."""
        self._closed = True
        with self._lock:
            self._ingest_token = None
            self._ingest_connected = False
        self.stop()

    # -------------------------------------------------------------- internals

    def _spawn(self, kind: PlaybackKind, label: str, input_args: list[str],
               stdin, volume: float, loop: bool,
               temp_file: Optional[Path] = None) -> None:
        """Start `ffmpeg | pacat` feeding this session's mic sink."""
        if self._closed:
            raise PlaybackUnavailable("This session's microphone is gone")

        with self._lock:
            if self._is_alive(self._current):
                raise PlaybackBusy(
                    f"Already playing ({self._current.kind.value}); stop it first"
                )

        pacat = subprocess.Popen(
            [
                "pacat",
                f"--device={self.sink_name}",
                "--format=s16le",
                f"--rate={DEFAULT_SAMPLE_RATE}",
                f"--channels={DEFAULT_CHANNELS}",
                f"--client-name=teams-mic-{self.session_id[:8]}",
            ],
            stdin=subprocess.PIPE,
        )

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", *input_args, "-vn"]
        if volume != 1.0:
            cmd += ["-filter:a", f"volume={volume}"]
        cmd += [
            "-ac", str(DEFAULT_CHANNELS),
            "-ar", str(DEFAULT_SAMPLE_RATE),
            "-f", "s16le", "pipe:1",
        ]

        try:
            ffmpeg = subprocess.Popen(
                cmd, stdin=stdin, stdout=pacat.stdin, stderr=subprocess.PIPE
            )
        except FileNotFoundError:
            pacat.kill()
            raise PlaybackUnavailable(
                "ffmpeg is not installed in this image; microphone playback needs it"
            )
        finally:
            # The parent's copy of pacat's stdin has to go, or pacat never sees
            # EOF when ffmpeg exits and sits there holding the sink open.
            pacat.stdin.close()

        playback = _Playback(
            kind=kind,
            label=label,
            ffmpeg=ffmpeg,
            pacat=pacat,
            started_at=datetime.now(),
            loop=loop,
            temp_file=temp_file,
        )
        with self._lock:
            self._current = playback

        threading.Thread(
            target=self._watch, args=(playback,), daemon=True,
            name=f"mic-watch-{self.session_id[:8]}",
        ).start()

        logger.info(f"[{self.session_id}] Playing {kind.value}: {label} -> {self.sink_name}")

    def _watch(self, playback: _Playback) -> None:
        """Reap one pipeline and clear it from the player when it ends."""
        stderr = b""
        try:
            if playback.ffmpeg.stderr:
                stderr = playback.ffmpeg.stderr.read() or b""
        except Exception:
            pass
        playback.ffmpeg.wait()

        try:
            playback.pacat.wait(timeout=self.TERMINATE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            playback.pacat.kill()

        if stderr and not playback.stopped:
            logger.warning(
                f"[{self.session_id}] ffmpeg: {stderr.decode(errors='replace').strip()}"
            )

        if playback.temp_file:
            try:
                playback.temp_file.unlink(missing_ok=True)
            except OSError as e:
                logger.warning(f"Could not remove {playback.temp_file}: {e}")

        with self._lock:
            if self._current is playback:
                self._current = None
                # A stream whose decoder died is no longer ingestable, so retire
                # the token with it rather than leave a URL that only 500s.
                if playback.kind is PlaybackKind.STREAM:
                    self._ingest_token = None
                    self._ingest_connected = False

        if not playback.stopped:
            logger.info(f"[{self.session_id}] Playback finished: {playback.label}")

    def _terminate(self, playback: _Playback) -> None:
        """End a pipeline, closing the ingest pipe first so ffmpeg sees EOF."""
        if playback.ffmpeg.stdin:
            try:
                playback.ffmpeg.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        for proc in (playback.ffmpeg, playback.pacat):
            if proc.poll() is not None:
                continue
            proc.terminate()
            try:
                proc.wait(timeout=self.TERMINATE_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                proc.kill()
