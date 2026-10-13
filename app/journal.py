"""What a running session would need to be finished off after a crash.

Sessions live in memory. If the process dies (a crash, a container restart, a
redeploy) they are gone, and with them the only record that a recording was in
progress. Each active session therefore keeps a small file next to the
recordings; a file still there on the next start belongs to a session that
never finished, and startup recovery deals with it (see app.recovery).
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from app.config import RECORDINGS_DIR

logger = logging.getLogger(__name__)


def journal_dir() -> Path:
    return Path(RECORDINGS_DIR) / ".sessions"


def write(session_id: str, state: Dict[str, Any]) -> None:
    """Store a session's state. Atomic: a crash mid-write leaves the old file, never half a new one."""
    directory = journal_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{session_id}.json"
    tmp = directory / f".{session_id}.json.tmp"
    tmp.write_text(json.dumps(state, default=str), encoding="utf-8")
    os.replace(tmp, target)


def remove(session_id: str) -> None:
    (journal_dir() / f"{session_id}.json").unlink(missing_ok=True)


def load_all() -> List[Dict[str, Any]]:
    """Every session that was still running when the process last stopped."""
    directory = journal_dir()
    if not directory.exists():
        return []
    entries = []
    for path in sorted(directory.glob("*.json")):
        try:
            entries.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            # Unreadable means it cannot be recovered either; keep it for a human.
            logger.error(f"Unreadable session journal {path.name}: {e}")
    return entries
