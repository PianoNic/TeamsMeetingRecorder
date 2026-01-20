"""Utility functions for Teams Meeting Recorder."""

import logging
import subprocess
from pathlib import Path

from app.config import settings, RECORDINGS_DIR

logger = logging.getLogger(__name__)


def save_screenshot(session_id: str, label: str) -> None:
    """
    Save a screenshot if debug mode is enabled.

    Args:
        session_id: The session ID for naming the screenshot
        label: A descriptive label for the screenshot (e.g., "before_join", "after_join")
    """
    if not settings.debug_screenshots:
        return

    screenshot_path = Path(RECORDINGS_DIR) / f"{session_id}_{label}.png"
    subprocess.run(["scrot", str(screenshot_path)], check=False)
    logger.info(f"Screenshot saved: {screenshot_path}")
