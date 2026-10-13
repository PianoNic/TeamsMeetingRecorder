"""Nothing a session reports may get lost: not to a busy receiver, not to a restart.

The outbox, the session journal and startup recovery all work on files under
RECORDINGS_DIR, which each test points at its own temporary directory. Sending
and uploading are faked.

Run: python -m pytest tests/
"""

import asyncio
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest
import soundfile as sf

from app import bot as bot_module
from app import journal, outbox, recovery
from app.bot import TeamsBot
from app.config import settings
from app.models import BotStatus

run = asyncio.run
MEETING = "https://teams.microsoft.com/l/meetup-join/abc"


@pytest.fixture(autouse=True)
def recordings(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "RECORDINGS_DIR", str(tmp_path))
    monkeypatch.setattr(outbox, "RECORDINGS_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "webhook_url", "http://receiver/hook")
    monkeypatch.setattr(settings, "webhook_events", False)
    monkeypatch.setattr(settings, "webhook_retry_hours", 24)
    return tmp_path


class Receiver:
    """Records what it got; answers with the next value of `answers` (True = 2xx)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.got = []

    async def __call__(self, url, payload):
        ok = self.answers.pop(0) if self.answers else True
        if ok:
            self.got.append(payload)
        return ok


class Storage:
    def __init__(self, ok=True):
        self.ok = ok
        self.uploads = []

    def uses_remote_storage(self):
        return True

    def upload_file(self, local, remote):
        self.uploads.append((local, remote))
        return self.ok

    def get_webhook_file_location(self, remote):
        return f"container/{remote}"


def _payload(session="s1", sequence=1, event="finished"):
    return {"session_id": session, "sequence": sequence, "event": event, "file_location": ""}


# --- outbox ---------------------------------------------------------------

def test_delivered_item_is_removed():
    outbox.enqueue(_payload())
    receiver = Receiver(True)

    assert run(outbox.deliver_due(receiver, Storage())) == 1
    assert receiver.got[0]["session_id"] == "s1"
    assert list(outbox.outbox_dir().glob("*.json")) == []


def test_failed_delivery_is_kept_and_retried_after_the_pause():
    path = outbox.enqueue(_payload())
    receiver = Receiver(False, True)

    run(outbox.deliver_due(receiver, Storage(), now=1000))
    item = json.loads(path.read_text())
    assert item["attempts"] == 1
    assert item["next_attempt"] == 1000 + outbox.FIRST_RETRY_SECONDS

    run(outbox.deliver_due(receiver, Storage(), now=1001))  # too early
    assert receiver.got == []

    run(outbox.deliver_due(receiver, Storage(), now=1000 + outbox.FIRST_RETRY_SECONDS))
    assert len(receiver.got) == 1
    assert not path.exists()


def test_retry_pauses_grow_and_are_capped():
    assert [outbox._backoff(n) for n in (1, 2, 3)] == [5, 10, 20]
    assert outbox._backoff(30) == outbox.MAX_RETRY_SECONDS


def test_a_session_is_delivered_in_order_others_are_not_held_up():
    outbox.enqueue(_payload("s1", 1, "status"))
    outbox.enqueue(_payload("s1", 2, "finished"))
    outbox.enqueue(_payload("s2", 1, "finished"))
    receiver = Receiver(False, True)  # s1#1 fails, s2#1 goes through

    run(outbox.deliver_due(receiver, Storage(), now=0))

    assert [(p["session_id"], p["sequence"]) for p in receiver.got] == [("s2", 1)]
    assert len(list(outbox.outbox_dir().glob("s1_*.json"))) == 2


def test_given_up_after_the_retry_window_and_kept_for_a_human():
    path = outbox.enqueue(_payload())
    item = json.loads(path.read_text())
    item["created"] = 0
    path.write_text(json.dumps(item))

    run(outbox.deliver_due(Receiver(False), Storage(), now=25 * 3600))

    assert not path.exists()
    assert (outbox.outbox_dir() / "failed" / path.name).exists()


def test_upload_happens_before_the_webhook_and_names_the_uploaded_file(recordings):
    local = recordings / "rec.flac"
    local.write_bytes(b"fLaC")
    outbox.enqueue(_payload(), upload_from=str(local), upload_to="s1/rec.flac")
    receiver, storage = Receiver(True), Storage(ok=True)

    run(outbox.deliver_due(receiver, storage))

    assert storage.uploads == [(str(local), "s1/rec.flac")]
    assert receiver.got[0]["file_location"] == "container/s1/rec.flac"
    assert not local.exists()


def test_failed_upload_is_retried_and_no_webhook_points_at_a_local_file(recordings):
    local = recordings / "rec.flac"
    local.write_bytes(b"fLaC")
    path = outbox.enqueue(_payload(), upload_from=str(local), upload_to="s1/rec.flac")
    receiver = Receiver(True)

    run(outbox.deliver_due(receiver, Storage(ok=False), now=0))

    assert receiver.got == []
    assert local.exists()
    assert json.loads(path.read_text())["attempts"] == 1


def test_upload_done_before_a_crash_is_not_repeated(recordings):
    path = outbox.enqueue(_payload(), upload_from=str(recordings / "gone.flac"), upload_to="s1/gone.flac")
    receiver, storage = Receiver(True), Storage()

    run(outbox.deliver_due(receiver, storage))  # the local file is already gone: it was uploaded

    assert storage.uploads == []
    assert receiver.got[0]["file_location"] == "container/s1/gone.flac"
    assert not path.exists()


# --- journal ----------------------------------------------------------------

def test_journal_round_trip():
    journal.write("s1", {"session_id": "s1", "status": "recording"})
    assert journal.load_all() == [{"session_id": "s1", "status": "recording"}]
    journal.remove("s1")
    assert journal.load_all() == []


# --- the bot's status changes ----------------------------------------------

@pytest.fixture
def local_storage(monkeypatch):
    class Local:
        def uses_remote_storage(self):
            return False

    monkeypatch.setattr(bot_module, "get_storage", lambda: Local())


def _items():
    return [json.loads(p.read_text())["payload"] for p in sorted(outbox.outbox_dir().glob("*.json"))]


def test_progress_is_journaled_but_only_reported_when_asked(local_storage):
    b = TeamsBot(MEETING, "Bot", reference="ref-1")
    b._set_status(BotStatus.LOBBY)

    assert journal.load_all()[0]["status"] == "lobby"
    assert journal.load_all()[0]["reference"] == "ref-1"
    assert _items() == []


def test_progress_events_carry_status_reference_and_sequence(local_storage, monkeypatch):
    monkeypatch.setattr(settings, "webhook_events", True)
    b = TeamsBot(MEETING, "Bot", reference="ref-1")

    b._set_status(BotStatus.JOINING)
    b._set_status(BotStatus.LOBBY)
    b._set_status(BotStatus.RECORDING)

    items = _items()
    assert [(i["event"], i["status"], i["sequence"]) for i in items] == [
        ("status", "joining", 1), ("status", "lobby", 2), ("status", "recording", 3),
    ]
    assert all(i["reference"] == "ref-1" for i in items)


def test_finished_is_reported_once_with_its_status_and_clears_the_journal(local_storage):
    b = TeamsBot(MEETING, "Bot")
    b._set_status(BotStatus.LOBBY)
    b.status = BotStatus.DENIED
    b.error_message = "Denied entry to the meeting"

    b._finish()
    b._finish()

    finished = [i for i in _items() if i["event"] == "finished"]
    assert len(finished) == 1
    assert finished[0]["status"] == "denied"
    assert finished[0]["error_message"] == "Denied entry to the meeting"
    assert journal.load_all() == []


# --- startup recovery -------------------------------------------------------

@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_interrupted_session_is_reported_with_its_repaired_recording(recordings, monkeypatch):
    class Local:
        def uses_remote_storage(self):
            return False

    monkeypatch.setattr(recovery, "get_storage", lambda: Local())
    monkeypatch.setattr(recovery, "_unload_modules", lambda names: None)

    # What a killed writer leaves: samples on disk, a header that was never finalised.
    rec = recordings / "s1_rec.wav"
    samples = (np.sin(np.arange(48000) / 10) * 8000).astype(np.int16).repeat(2).reshape(-1, 2)
    sf.write(str(rec), samples, 48000, subtype="PCM_16")
    data = bytearray(rec.read_bytes())
    data[4:8] = b"\x00\x00\x00\x00"    # RIFF size
    data[40:44] = b"\x00\x00\x00\x00"  # data size
    rec.write_bytes(bytes(data))
    journal.write("s1", {
        "session_id": "s1", "reference": "ref-1", "meeting_url": MEETING,
        "status": "recording", "sequence": 3, "recording_file": str(rec), "started_at": "2026-01-01T09:00:00",
    })

    assert recovery.recover_interrupted_sessions() == 1

    item = _items()[0]
    assert item["event"] == "finished"
    assert item["status"] == "interrupted"
    assert item["reference"] == "ref-1"
    assert item["sequence"] == 4
    assert item["file_location"] == str(rec)
    read, rate = sf.read(str(rec), dtype="int16", always_2d=True)
    assert rate == 48000 and read.shape == samples.shape
    assert journal.load_all() == []


def test_interrupted_session_without_recording_is_still_reported(recordings, monkeypatch):
    monkeypatch.setattr(recovery, "_unload_modules", lambda names: None)
    journal.write("s2", {"session_id": "s2", "reference": "ref-2", "status": "lobby", "sequence": 1})

    recovery.recover_interrupted_sessions()

    item = _items()[0]
    assert (item["status"], item["file_location"], item["reference"]) == ("interrupted", "", "ref-2")
