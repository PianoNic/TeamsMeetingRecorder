"""Webhooks that survive a busy receiver, a lost connection and a restart.

A webhook used to be one POST: if the receiver was down for a moment (a
redeploy is enough) the news that a recording exists was lost for good. Now
every webhook is written to disk first and delivered from there:

- Retried with growing pauses until the receiver answers 2xx, across restarts.
- In order per session: a later event for a session waits until the earlier
  one is through, so the receiver never sees "finished" before "lobby".
- A recording that still has to be uploaded is uploaded by the same item,
  right before its webhook, so the webhook never points at a file the receiver
  cannot reach.
- After WEBHOOK_RETRY_HOURS an item is given up on and moved to
  `.outbox/failed/`, where it stays for a human instead of vanishing.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.config import RECORDINGS_DIR, settings

logger = logging.getLogger(__name__)

# Pause before the n-th retry: 5 s doubling, capped at 10 minutes.
FIRST_RETRY_SECONDS = 5
MAX_RETRY_SECONDS = 600
POLL_SECONDS = 2

Sender = Callable[[str, Dict[str, Any]], Awaitable[bool]]


def outbox_dir() -> Path:
    return Path(RECORDINGS_DIR) / ".outbox"


def enqueue(
    payload: Dict[str, Any],
    upload_from: Optional[str] = None,
    upload_to: Optional[str] = None,
) -> Path:
    """Persist one webhook. With upload_from/upload_to the file is uploaded before it is sent."""
    directory = outbox_dir()
    directory.mkdir(parents=True, exist_ok=True)
    item = {
        "payload": payload,
        "upload_from": upload_from,
        "upload_to": upload_to,
        "created": time.time(),
        "attempts": 0,
        "next_attempt": 0.0,
    }
    # Name sorts by session, then sequence: the delivery order.
    name = f"{payload['session_id']}_{int(payload.get('sequence') or 0):06d}.json"
    path = directory / name
    _write(path, item)
    return path


def _write(path: Path, item: Dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(item, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _pending() -> List[Path]:
    directory = outbox_dir()
    if not directory.exists():
        return []
    return sorted(p for p in directory.glob("*.json"))


def _backoff(attempts: int) -> float:
    return min(FIRST_RETRY_SECONDS * (2 ** max(attempts - 1, 0)), MAX_RETRY_SECONDS)


async def deliver_due(send: Sender, storage, now: Optional[float] = None) -> int:
    """One pass over the outbox. Returns how many items were delivered."""
    now = time.time() if now is None else now
    delivered = 0
    blocked_sessions = set()

    for path in _pending():
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.error(f"Unreadable outbox item {path.name}, moving aside: {e}")
            _give_up(path)
            continue

        session_id = item["payload"].get("session_id")
        if session_id in blocked_sessions:
            continue  # an earlier event of this session is still waiting
        if item.get("next_attempt", 0) > now:
            blocked_sessions.add(session_id)
            continue

        if await _attempt(path, item, send, storage, now):
            path.unlink(missing_ok=True)
            delivered += 1
        else:
            blocked_sessions.add(session_id)
    return delivered


async def _attempt(path: Path, item: Dict[str, Any], send: Sender, storage, now: float) -> bool:
    payload = item["payload"]

    if item.get("upload_from"):
        local = item["upload_from"]
        if Path(local).exists():
            ok = await asyncio.to_thread(storage.upload_file, local, item["upload_to"])
            if not ok:
                return _failed(path, item, now, "upload")
            payload["file_location"] = storage.get_webhook_file_location(item["upload_to"])
            try:
                Path(local).unlink(missing_ok=True)
            except OSError as e:
                logger.warning(f"Uploaded but could not remove {local}: {e}")
        elif not payload.get("file_location"):
            # Uploaded on an earlier attempt that crashed before writing that down.
            payload["file_location"] = storage.get_webhook_file_location(item["upload_to"])
        item["upload_from"] = None
        _write(path, item)  # the upload is done; a crash from here on must not redo it

    if not settings.webhook_url:
        return True  # nobody to tell; the upload above was the work

    if await send(settings.webhook_url, payload):
        return True
    return _failed(path, item, now, "webhook")


def _failed(path: Path, item: Dict[str, Any], now: float, what: str) -> bool:
    item["attempts"] = item.get("attempts", 0) + 1
    age_hours = (now - item.get("created", now)) / 3600
    if age_hours >= settings.webhook_retry_hours:
        logger.error(
            f"Giving up on {path.name} after {item['attempts']} attempts over {age_hours:.1f} h "
            f"({what} kept failing); kept in {outbox_dir() / 'failed'}"
        )
        _write(path, item)
        _give_up(path)
        return False
    item["next_attempt"] = now + _backoff(item["attempts"])
    _write(path, item)
    logger.warning(f"{what} for {path.name} failed (attempt {item['attempts']}), retrying in {_backoff(item['attempts']):.0f} s")
    return False


def _give_up(path: Path) -> None:
    failed = outbox_dir() / "failed"
    failed.mkdir(parents=True, exist_ok=True)
    os.replace(path, failed / path.name)


async def run_forever(send: Sender, storage_factory) -> None:
    """The delivery loop the app starts once. Never raises: a bad pass is logged and the next one runs."""
    while True:
        try:
            await deliver_due(send, storage_factory())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Outbox pass failed: {e}")
        await asyncio.sleep(POLL_SECONDS)
