"""Finding a session again: by the meeting it is in and by the caller's reference.

A caller that lost the response to POST /join (a timeout, a restart) has no
session id. With a reference it can send the same /join again and get the
session that did start, instead of a second bot in the meeting; /sessions,
/status and the webhook name the meeting and the reference so the caller can
match every report to its own record.

Run: python -m pytest tests/
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.bot import TeamsBot
from app.models import BotStatus
from app.webhook import WebhookPayload

MEETING = "https://teams.microsoft.com/l/meetup-join/abc"


@pytest.fixture
def client(monkeypatch):
    # /join would launch a browser; the session only has to be registered.
    async def no_start(self):
        self.status = BotStatus.JOINING

    monkeypatch.setattr(TeamsBot, "start", no_start)
    with TestClient(main_module.app) as c:
        yield c
    main_module.active_sessions.clear()
    main_module.finished_sessions.clear()


def _bot(status=BotStatus.RECORDING, reference=None):
    b = TeamsBot(MEETING, "Recorder", reference=reference)
    b.status = status
    return b


def _join(client, reference=None, meeting=MEETING):
    body = {"meeting_url": meeting, "display_name": "Recorder"}
    if reference is not None:
        body["reference"] = reference
    r = client.post("/join", json=body)
    assert r.status_code == 200
    return r.json()["session"]


def test_sessions_list_the_meeting_and_the_reference(client):
    b = _bot(reference="ref-1")
    main_module.active_sessions[b.session_id] = b

    sessions = client.get("/sessions").json()

    assert sessions == [
        {
            "session_id": b.session_id,
            "meeting_url": MEETING,
            "reference": "ref-1",
            "display_name": "Recorder",
            "status": "recording",
            "record": True,
            "uptime_seconds": b.get_uptime(),
            "started_at": None,
        }
    ]


def test_status_names_the_meeting_and_the_reference(client):
    b = _bot(reference="ref-1")
    main_module.active_sessions[b.session_id] = b

    body = client.get(f"/status/{b.session_id}").json()

    assert body["meeting_url"] == MEETING
    assert body["reference"] == "ref-1"


def test_status_still_names_the_meeting_after_the_session_ended(client):
    b = _bot(status=BotStatus.STOPPED, reference="ref-1")
    main_module.finished_sessions[b.session_id] = b

    body = client.get(f"/status/{b.session_id}").json()

    assert body["meeting_url"] == MEETING
    assert body["reference"] == "ref-1"


def test_join_with_the_same_reference_returns_the_running_session(client):
    first = _join(client, reference="ref-1")
    second = _join(client, reference="ref-1")

    assert second["session_id"] == first["session_id"]
    assert second["reference"] == "ref-1"
    assert len(main_module.active_sessions) == 1


def test_join_with_another_reference_sends_another_bot(client):
    first = _join(client, reference="ref-1")
    second = _join(client, reference="ref-2")

    assert second["session_id"] != first["session_id"]
    assert len(main_module.active_sessions) == 2


def test_join_without_reference_is_never_deduplicated(client):
    # Callers that do not send a reference keep the old behaviour exactly.
    first = _join(client)
    second = _join(client)

    assert second["session_id"] != first["session_id"]
    assert second["reference"] is None


def test_a_finished_session_does_not_block_a_new_join(client):
    old = _bot(status=BotStatus.STOPPED, reference="ref-1")
    main_module.finished_sessions[old.session_id] = old

    new = _join(client, reference="ref-1")

    assert new["session_id"] != old.session_id


def test_reference_is_too_long(client):
    r = client.post("/join", json={"meeting_url": MEETING, "display_name": "R", "reference": "x" * 201})
    assert r.status_code == 422


def test_webhook_carries_the_reference():
    payload = WebhookPayload(
        session_id="s",
        meeting_url=MEETING,
        reference="ref-1",
        file_location="recordings/s.wav",
        started_at=datetime(2026, 1, 1, 9, 0),
        stopped_at=datetime(2026, 1, 1, 10, 0),
    ).to_dict()

    assert payload["reference"] == "ref-1"
    assert payload["session_id"] == "s"


def test_webhook_without_reference_sends_null():
    payload = WebhookPayload(
        session_id="s",
        meeting_url=MEETING,
        file_location="",
        started_at=datetime(2026, 1, 1, 9, 0),
        stopped_at=datetime(2026, 1, 1, 10, 0),
    ).to_dict()

    assert payload["reference"] is None
