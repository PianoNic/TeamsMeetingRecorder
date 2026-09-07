"""The audio graph the bot builds, and the /audio endpoints on top of it.

Nothing here launches PulseAudio, ffmpeg or a browser: pactl is faked, the
Playwright page is faked, and sessions are inserted into the app's registry
directly. The point is the wiring - which sink the microphone reads from,
which modules get unloaded, and what each endpoint answers.

Run: python -m pytest tests/   or   python tests/test_audio_api.py
"""

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

# The coroutines under test are driven directly rather than through
# pytest-asyncio: it is not a declared dependency, and a clean checkout would
# silently skip every test that needed it.
run = asyncio.run

from app import bot as bot_module
from app import main as main_module
from app.bot import TeamsBot
from app.config import settings
from app.models import BotStatus


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakePactl:
    """Answers `pactl load-module` with incrementing module ids."""

    def __init__(self):
        self.calls = []
        self.next_id = 100

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if "load-module" in cmd:
            self.next_id += 1
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{self.next_id}\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def loaded(self, module):
        return [c for c in self.calls if "load-module" in c and module in c]

    @property
    def unloaded(self):
        return [c[2] for c in self.calls if c[1] == "unload-module"]


class FakeLocator:
    def __init__(self, page):
        self._page = page

    @property
    def first(self):
        return self

    async def get_attribute(self, name, timeout=None):
        if name == "aria-label":
            return "Unmute microphone" if self._page.muted else "Mute microphone"
        return None

    async def click(self, timeout=None):
        if self._page.click_is_a_noop:
            return
        self._page.muted = not self._page.muted
        self._page.clicks += 1

    async def is_visible(self, timeout=None):
        return True


class FakePageContext:
    async def close(self):
        pass


class FakePage:
    """Just enough Playwright page to drive the mute toggle."""

    def __init__(self, muted=True):
        self.muted = muted
        self.clicks = 0
        self.click_is_a_noop = False

    def locator(self, _selector):
        return FakeLocator(self)

    async def wait_for_timeout(self, _ms):
        pass

    async def close(self):
        pass


class _RecordingPage:
    """A page that records every selector asked for and nothing else.

    Used to prove a code path touches the DOM not at all, which is the whole
    guarantee behind "the default join path is unchanged".
    """

    def __init__(self):
        self.locators = []

    def locator(self, selector):
        self.locators.append(selector)
        raise AssertionError(f"the page should not have been touched: {selector}")


@pytest.fixture
def pactl(monkeypatch):
    fake = FakePactl()
    monkeypatch.setattr(bot_module.subprocess, "run", fake)
    return fake


@pytest.fixture
def media(tmp_path, monkeypatch):
    root = tmp_path / "media"
    root.mkdir()
    (root / "song.mp3").write_bytes(b"ID3fake")
    monkeypatch.setattr(settings, "media_dir", str(root))
    monkeypatch.setattr(main_module, "MEDIA_DIR", str(root))
    monkeypatch.setattr(main_module, "RECORDINGS_DIR", str(tmp_path / "recordings"))
    return root


def _bot(record=True, muted=True, status=BotStatus.RECORDING):
    b = TeamsBot("https://teams.microsoft.com/l/meetup-join/x", "Bot", record=record)
    b.page = FakePage(muted=muted)
    b.status = status
    return b


# --------------------------------------------------------------------------
# The audio graph
# --------------------------------------------------------------------------


def test_the_microphone_reads_from_its_own_sink_not_the_recording_one(pactl, monkeypatch):
    monkeypatch.setattr(settings, "mic_playback_enabled", True)
    monkeypatch.setattr(settings, "playback_in_recording", True)
    b = _bot()
    b.sink_name, b.monitor_name, b.sink_module_id = b._create_audio_sink()

    mic_source = b._create_mic_sink()

    # A real source, not a monitor: chromium does not enumerate monitor sources
    # at all, so `<sink>.monitor` would leave getUserMedia with no microphone.
    assert mic_source == b.mic_source_name
    assert not mic_source.endswith(".monitor")
    remap = pactl.loaded("module-remap-source")[0]
    assert f"master={b.mic_sink_name}.monitor" in remap
    assert f"source_name={mic_source}" in remap

    # Pointing the browser's microphone at the sink it also plays into would
    # feed the meeting straight back to itself the moment the bot unmutes.
    assert mic_source != b.monitor_name
    assert b.mic_player is not None


def test_playback_is_looped_into_the_recording(pactl, monkeypatch):
    monkeypatch.setattr(settings, "playback_in_recording", True)
    b = _bot(record=True)
    b.sink_name, b.monitor_name, b.sink_module_id = b._create_audio_sink()
    b._create_mic_sink()

    loopback = pactl.loaded("module-loopback")[0]
    assert f"source={b.mic_sink_name}.monitor" in loopback
    assert f"sink={b.sink_name}" in loopback
    assert b.loopback_module_id


def test_no_loopback_when_the_setting_is_off(pactl, monkeypatch):
    monkeypatch.setattr(settings, "playback_in_recording", False)
    b = _bot()
    b.sink_name, b.monitor_name, b.sink_module_id = b._create_audio_sink()
    b._create_mic_sink()

    assert pactl.loaded("module-loopback") == []
    assert b.loopback_module_id is None


def test_no_loopback_for_a_speak_only_session(pactl, monkeypatch):
    monkeypatch.setattr(settings, "playback_in_recording", True)
    b = _bot(record=False)
    b.sink_name, b.monitor_name, b.sink_module_id = b._create_audio_sink()
    b._create_mic_sink()

    # There is no recording to loop anything into.
    assert pactl.loaded("module-loopback") == []


def test_a_failed_loopback_does_not_sink_the_session(monkeypatch):
    def run(cmd, **kwargs):
        if "module-loopback" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr="no such sink")
        return subprocess.CompletedProcess(cmd, 0, stdout="7\n", stderr="")

    monkeypatch.setattr(bot_module.subprocess, "run", run)
    monkeypatch.setattr(settings, "playback_in_recording", True)
    b = _bot()
    b.sink_name, b.monitor_name, b.sink_module_id = b._create_audio_sink()

    # Only the recording loses the bot's own audio; the meeting is unaffected.
    b._create_mic_sink()
    assert b.loopback_module_id is None
    assert b.mic_player is not None


def test_the_browser_microphone_reads_the_mic_sink(pactl, monkeypatch):
    monkeypatch.setattr(settings, "mic_playback_enabled", True)
    b = _bot()
    b.sink_name, b.monitor_name, b.sink_module_id = b._create_audio_sink()
    mic_source = b._create_mic_sink()

    env, args = b._build_launch_options(mic_source)

    assert env["PULSE_SINK"] == b.sink_name           # meeting audio out
    assert env["PULSE_SOURCE"] == mic_source          # what the bot says
    assert env["PULSE_SOURCE"] != b.monitor_name
    # The fake device would replace the real capture device with a beep, so
    # nothing the bot played would ever reach the meeting.
    assert "--use-fake-device-for-media-stream" not in args


def test_disabling_mic_playback_restores_the_previous_wiring(pactl, monkeypatch):
    monkeypatch.setattr(settings, "mic_playback_enabled", False)
    b = _bot()
    b.sink_name, b.monitor_name, b.sink_module_id = b._create_audio_sink()

    env, args = b._build_launch_options(b.monitor_name)

    assert env["PULSE_SOURCE"] == b.monitor_name
    assert "--use-fake-device-for-media-stream" in args
    assert b.mic_player is None
    # Only the recording sink exists; no second sink was created.
    assert len(pactl.loaded("module-null-sink")) == 1


def test_the_default_join_path_never_touches_the_no_devices_prompt(monkeypatch):
    """With playback off there is still a fake camera, so no prompt can appear.

    Guards the join path that is known to work: the dismissal must not add a
    wait, a click, or a failure mode to it.
    """
    monkeypatch.setattr(settings, "mic_playback_enabled", False)
    b = _bot()
    b.page = _RecordingPage()

    run(b._dismiss_no_devices_prompt(b.NO_DEVICES_FIRST_WAIT_MS))

    assert b.page.locators == []


def test_the_default_join_path_leaves_noise_suppression_alone(monkeypatch):
    monkeypatch.setattr(settings, "mic_playback_enabled", False)
    monkeypatch.setattr(settings, "disable_noise_suppression", True)
    b = _bot()
    b.page = _RecordingPage()

    run(b._disable_noise_suppression())

    assert b.page.locators == []


def test_noise_suppression_can_be_left_on(monkeypatch):
    monkeypatch.setattr(settings, "mic_playback_enabled", True)
    monkeypatch.setattr(settings, "disable_noise_suppression", False)
    b = _bot()
    b.page = _RecordingPage()

    run(b._disable_noise_suppression())

    assert b.page.locators == []


def test_cleanup_unloads_the_loopback_before_the_sinks(pactl, monkeypatch):
    monkeypatch.setattr(settings, "playback_in_recording", True)
    b = _bot()
    b.sink_name, b.monitor_name, b.sink_module_id = b._create_audio_sink()
    b._create_mic_sink()
    b.page = None

    run(b.cleanup())

    # The loopback references both sinks; unloading a sink first would leave a
    # dangling module behind.
    assert pactl.unloaded == [
        b.loopback_module_id,
        b.mic_source_module_id,
        b.mic_module_id,
        b.sink_module_id,
    ]


# --------------------------------------------------------------------------
# Mute control
# --------------------------------------------------------------------------


def test_reading_the_mute_state_from_the_button_label():
    b = _bot(muted=True)
    assert run(b._read_muted()) is True
    b.page.muted = False
    assert run(b._read_muted()) is False


def test_unmuting_clicks_once():
    b = _bot(muted=True)
    assert run(b.set_muted(False)) is False
    assert b.page.clicks == 1
    assert b.page.muted is False


def test_setting_the_state_it_is_already_in_does_not_click():
    b = _bot(muted=False)
    # A blind toggle here would mute the bot mid-sentence.
    assert run(b.set_muted(False)) is False
    assert b.page.clicks == 0


def test_a_click_that_changes_nothing_is_reported_as_a_failure():
    b = _bot(muted=True)
    b.page.click_is_a_noop = True
    b.MUTE_VERIFY_ATTEMPTS = 1

    with pytest.raises(RuntimeError, match="did not unmute"):
        run(b.set_muted(False))


def test_mute_control_needs_to_be_in_a_meeting():
    b = _bot(status=BotStatus.JOINING)
    with pytest.raises(RuntimeError, match="Not in a meeting"):
        run(b.set_muted(False))


def test_a_speak_only_session_still_counts_as_in_a_meeting():
    b = _bot(record=False, status=BotStatus.CONNECTED)
    assert run(b.set_muted(False)) is False
    assert b.page.clicks == 1


# --------------------------------------------------------------------------
# The HTTP surface
# --------------------------------------------------------------------------


@pytest.fixture
def client(media, monkeypatch):
    monkeypatch.setattr(settings, "mic_playback_enabled", True)
    monkeypatch.setattr(settings, "bot_access_token", None)
    main_module.active_sessions.clear()
    main_module.finished_sessions.clear()
    with TestClient(main_module.app) as c:
        yield c
    main_module.active_sessions.clear()


@pytest.fixture
def session(client, pactl, monkeypatch, spawn):
    b = _bot()
    b.sink_name, b.monitor_name, b.sink_module_id = b._create_audio_sink()
    b._create_mic_sink()
    main_module.active_sessions[b.session_id] = b
    return b


class _Spawner:
    def __init__(self):
        self.procs = []

    def __call__(self, cmd, **kwargs):
        from test_mic_playback import FakeProc
        proc = FakeProc(cmd, **kwargs)
        self.procs.append(proc)
        return proc

    def of(self, program):
        return [p for p in self.procs if p.cmd[0] == program]


@pytest.fixture
def spawn(monkeypatch):
    from app import audio_out
    s = _Spawner()
    monkeypatch.setattr(audio_out.subprocess, "Popen", s)
    return s


def test_audio_state_of_a_live_session(client, session):
    r = client.get(f"/audio/{session.session_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["muted"] is True
    assert body["playing"] is False
    assert body["record"] is True
    assert body["status"] == "recording"


def test_audio_state_of_an_unknown_session_is_404(client):
    assert client.get("/audio/nope").status_code == 404


def test_unmute_and_mute_round_trip(client, session):
    assert client.post(f"/audio/{session.session_id}/unmute").json()["state"]["muted"] is False
    assert client.post(f"/audio/{session.session_id}/mute").json()["state"]["muted"] is True


def test_audio_endpoints_reject_a_session_that_is_not_in_a_meeting(client, session):
    session.status = BotStatus.JOINING
    r = client.post(f"/audio/{session.session_id}/unmute")
    assert r.status_code == 409
    assert "not in a meeting" in r.json()["detail"]


def test_play_a_file_from_the_media_directory(client, session, spawn):
    r = client.post(f"/audio/{session.session_id}/play", json={"path": "song.mp3"})
    assert r.status_code == 200
    body = r.json()
    assert body["state"]["playing"] is True
    assert body["state"]["kind"] == "file"
    # unmute defaults to true, so the meeting can actually hear it.
    assert body["state"]["muted"] is False
    assert spawn.of("ffmpeg")


def test_play_refuses_a_path_outside_the_media_directory(client, session, spawn):
    r = client.post(f"/audio/{session.session_id}/play", json={"path": "../../etc/passwd"})
    assert r.status_code == 400
    assert spawn.of("ffmpeg") == []


def test_play_refuses_a_second_track(client, session, spawn):
    client.post(f"/audio/{session.session_id}/play", json={"path": "song.mp3"})
    r = client.post(f"/audio/{session.session_id}/play", json={"path": "song.mp3"})
    assert r.status_code == 409


def test_play_can_be_told_not_to_unmute(client, session, spawn):
    r = client.post(
        f"/audio/{session.session_id}/play",
        json={"path": "song.mp3", "unmute": False},
    )
    assert r.json()["state"]["muted"] is True


def test_stop_playback(client, session, spawn):
    client.post(f"/audio/{session.session_id}/play", json={"path": "song.mp3"})
    r = client.post(f"/audio/{session.session_id}/stop", params={"mute_after": True})
    assert r.status_code == 200
    assert r.json()["state"]["playing"] is False
    assert r.json()["state"]["muted"] is True


def test_upload_and_play(client, session, spawn):
    r = client.post(
        f"/audio/{session.session_id}/play/upload",
        files={"file": ("greeting.mp3", b"ID3" + b"\x00" * 64, "audio/mpeg")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"]["playing"] is True
    # The upload landed inside the media directory, not next to it.
    played = spawn.of("ffmpeg")[0].cmd
    target = Path(played[played.index("-i") + 1])
    assert target.parent.name == "uploads"
    assert target.exists()


def test_upload_over_the_size_limit_is_refused_and_leaves_nothing_behind(
    client, session, spawn, media, monkeypatch
):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    r = client.post(
        f"/audio/{session.session_id}/play/upload",
        files={"file": ("big.mp3", b"x" * 4096, "audio/mpeg")},
    )
    assert r.status_code == 413
    assert list((media / "uploads").glob("*")) == []
    assert spawn.of("ffmpeg") == []


# --------------------------------------------------------------------------
# Ingest streaming over HTTP
# --------------------------------------------------------------------------


def test_open_stream_returns_a_usable_ingest_url(client, session, spawn):
    r = client.post(f"/audio/{session.session_id}/stream", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ingest_url"].endswith(f"/audio/{session.session_id}/ingest/{body['token']}")
    assert session.mic_player.token_matches(body["token"])


def test_public_base_url_overrides_the_request_host(client, session, spawn, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://bot.example.com/")
    r = client.post(f"/audio/{session.session_id}/stream", json={})
    assert r.json()["ingest_url"].startswith("https://bot.example.com/audio/")


def test_pushed_bytes_reach_the_decoder(client, session, spawn):
    url = client.post(f"/audio/{session.session_id}/stream", json={}).json()["ingest_url"]
    r = client.put(url, content=b"\x01\x02\x03\x04")

    assert r.status_code == 200
    assert r.json() == {"success": True, "bytes_received": 4, "message": "Stream ended"}
    assert spawn.of("ffmpeg")[0].stdin.written == b"\x01\x02\x03\x04"


def test_ingest_accepts_post_as_well_as_put(client, session, spawn):
    url = client.post(f"/audio/{session.session_id}/stream", json={}).json()["ingest_url"]
    assert client.post(url, content=b"abcd").status_code == 200


def test_a_wrong_ingest_token_is_a_404(client, session, spawn):
    client.post(f"/audio/{session.session_id}/stream", json={})
    r = client.put(f"/audio/{session.session_id}/ingest/not-the-token", content=b"x")
    assert r.status_code == 404
    assert spawn.of("ffmpeg")[0].stdin.written == b""


def test_ingest_into_an_unknown_session_is_a_404(client):
    assert client.put("/audio/nope/ingest/whatever", content=b"x").status_code == 404


def test_closing_the_stream_invalidates_its_url(client, session, spawn):
    url = client.post(f"/audio/{session.session_id}/stream", json={}).json()["ingest_url"]
    assert client.delete(f"/audio/{session.session_id}/stream").status_code == 200
    assert client.put(url, content=b"x").status_code == 404


def test_the_ingest_url_works_without_the_api_token(client, session, spawn, monkeypatch):
    """The URL is meant to be handed to another application on its own."""
    url = client.post(f"/audio/{session.session_id}/stream", json={}).json()["ingest_url"]
    monkeypatch.setattr(settings, "bot_access_token", "s3cret")

    # Every other endpoint is now closed...
    assert client.get(f"/audio/{session.session_id}").status_code == 401
    # ...but the ingest URL carries its own secret.
    assert client.put(url, content=b"abcd").status_code == 200


def test_a_bad_ingest_token_is_still_a_404_not_a_401(client, session, spawn, monkeypatch):
    """Exempting the path must not turn it into an oracle."""
    client.post(f"/audio/{session.session_id}/stream", json={}).json()
    monkeypatch.setattr(settings, "bot_access_token", "s3cret")
    assert client.put(f"/audio/{session.session_id}/ingest/guess", content=b"x").status_code == 404


# --------------------------------------------------------------------------
# Speak-only sessions
# --------------------------------------------------------------------------


def test_join_defaults_to_recording(client, monkeypatch):
    captured = {}

    async def fake_start(self):
        captured["record"] = self.record
        self.status = BotStatus.RECORDING

    monkeypatch.setattr(TeamsBot, "start", fake_start)
    r = client.post("/join", json={
        "meeting_url": "https://teams.microsoft.com/l/meetup-join/x",
        "display_name": "Bot",
    })
    assert r.status_code == 200
    assert r.json()["session"]["record"] is True


def test_join_can_opt_out_of_recording(client, monkeypatch):
    async def fake_start(self):
        self.status = BotStatus.CONNECTED

    monkeypatch.setattr(TeamsBot, "start", fake_start)
    r = client.post("/join", json={
        "meeting_url": "https://teams.microsoft.com/l/meetup-join/x",
        "display_name": "Bot",
        "record": False,
    })
    assert r.json()["session"]["record"] is False


def test_a_speak_only_session_records_nothing(pactl, monkeypatch):
    b = _bot(record=False)
    started = []
    monkeypatch.setattr(
        bot_module, "AudioRecorder",
        lambda **kw: started.append(kw) or pytest.fail("recorder built for a speak-only session"),
    )

    b._start_audio_recording()

    assert b.status is BotStatus.CONNECTED
    assert b.recording_file is None
    assert started == []
    # The stay-in-the-meeting cap still applies, so it cannot sit there forever.
    assert b.recording_started_at is not None


def test_a_speak_only_session_can_still_use_the_microphone(client, pactl, spawn, monkeypatch):
    b = _bot(record=False, status=BotStatus.CONNECTED)
    b.sink_name, b.monitor_name, b.sink_module_id = b._create_audio_sink()
    b._create_mic_sink()
    main_module.active_sessions[b.session_id] = b

    r = client.post(f"/audio/{b.session_id}/play", json={"path": "song.mp3"})
    assert r.status_code == 200
    assert r.json()["state"]["record"] is False
    assert r.json()["state"]["playing"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
