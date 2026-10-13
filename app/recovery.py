"""Finishing off sessions a crash or restart left behind.

Runs once at startup, before any new session exists. For every session still in
the journal:

1. Its PulseAudio modules are unloaded. After a container restart there are
   none; after only the app restarted they would otherwise pile up.
2. The recording made so far is repaired: the writer never closed it, so the
   header claims a length of zero. ffmpeg reads the samples up to the cut and
   writes a valid file of the same format.
3. It is reported as `interrupted` through the outbox, with the repaired file,
   so the receiver learns about the session and gets every second recorded.
"""

import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app import journal, outbox
from app.config import settings
from app.models import BotStatus
from app.storage import get_storage

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "Interrupted: the recorder stopped while this session was running"


def recover_interrupted_sessions() -> int:
    """Report every session left in the journal as interrupted. Returns how many there were."""
    entries = journal.load_all()
    for state in entries:
        session_id = state.get("session_id")
        if not session_id:
            continue
        try:
            _recover(state)
        except Exception as e:
            # One broken leftover must not keep the others, or the app, from coming up.
            logger.error(f"Recovering session {session_id} failed: {e}")
        finally:
            journal.remove(session_id)
    if entries:
        logger.warning(f"Recovered {len(entries)} session(s) interrupted by the last stop")
    return len(entries)


def _recover(state: Dict[str, Any]) -> None:
    session_id = state["session_id"]
    _unload_modules([state.get(k) for k in ("sink_name", "mic_sink_name", "mic_source_name")])

    recording = state.get("recording_file")
    upload_from: Optional[str] = None
    upload_to: Optional[str] = None
    file_location = ""
    if recording and Path(recording).exists() and Path(recording).stat().st_size > 0:
        _repair(recording)
        storage = get_storage()
        if storage.uses_remote_storage() and state.get("storage_path"):
            upload_from, upload_to = recording, state["storage_path"]
        else:
            file_location = recording

    sequence = int(state.get("sequence") or 0) + 1
    outbox.enqueue(
        {
            "event": "finished",
            "session_id": session_id,
            "meeting_url": state.get("meeting_url"),
            "reference": state.get("reference"),
            "status": BotStatus.INTERRUPTED.value,
            "error_message": INTERRUPTED_MESSAGE,
            "file_location": file_location,
            "started_at": state.get("started_at"),
            "stopped_at": datetime.now().isoformat(),
            "sequence": sequence,
            "occurred_at": datetime.now().isoformat(),
        },
        upload_from=upload_from,
        upload_to=upload_to,
    )
    logger.warning(
        f"Session {session_id} was interrupted; reporting it"
        + (f" with its recording {recording}" if upload_from or file_location else " without a recording")
    )


def _unload_modules(names: List[Optional[str]]) -> None:
    names = [n for n in names if n]
    if not names:
        return
    try:
        listing = subprocess.run(
            ["pactl", "list", "short", "modules"], capture_output=True, text=True, check=False, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"Could not list PulseAudio modules: {e}")
        return
    for line in listing.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and any(f"={name}" in parts[2] or f"{name}.monitor" in parts[2] for name in names):
            subprocess.run(["pactl", "unload-module", parts[0]], check=False)
            logger.info(f"Unloaded leftover PulseAudio module {parts[0]} ({parts[1]})")


def _repair(recording: str) -> None:
    """Rewrite an unfinished recording so its header matches the samples that are there."""
    if not shutil.which("ffmpeg"):
        logger.warning(f"ffmpeg not found; leaving {recording} as written")
        return
    path = Path(recording)
    fixed = path.with_name(f".{path.stem}.repaired{path.suffix}")
    codec = "flac" if path.suffix.lower() == ".flac" else "pcm_s16le"
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-c:a", codec, str(fixed)],
        capture_output=True, text=True, check=False, timeout=600,
    )
    if result.returncode == 0 and fixed.exists() and fixed.stat().st_size > 0:
        fixed.replace(path)
        logger.info(f"Repaired interrupted recording {path.name}")
    else:
        fixed.unlink(missing_ok=True)
        logger.warning(f"Could not repair {path.name}, keeping it as written: {result.stderr.strip()[:300]}")
