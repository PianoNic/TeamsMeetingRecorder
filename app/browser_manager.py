"""Shared browser manager for handling multiple meetings simultaneously."""

import asyncio
import logging
import os
import subprocess
from typing import Optional, Dict
from playwright.async_api import async_playwright, Browser, Playwright

from app.config import settings, DISPLAY_NUMBER, DISPLAY_WIDTH, DISPLAY_HEIGHT

logger = logging.getLogger(__name__)


class BrowserManager:
    """Singleton manager for shared browser instance."""

    _instance: Optional['BrowserManager'] = None
    _lock = asyncio.Lock()

    def __init__(self):
        """Initialize browser manager."""
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.is_initialized = False
        self._audio_sink_counter = 0
        self._active_sinks: Dict[str, str] = {}  # session_id -> sink_name

    @classmethod
    async def get_instance(cls) -> 'BrowserManager':
        """Get or create the singleton browser manager instance."""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = BrowserManager()
                    await cls._instance._initialize()
        return cls._instance

    async def _initialize(self):
        """Initialize the shared browser instance."""
        if self.is_initialized:
            return

        logger.info("Initializing shared browser instance")
        os.environ["DISPLAY"] = f":{DISPLAY_NUMBER}"

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                f"--window-size={DISPLAY_WIDTH},{DISPLAY_HEIGHT}",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=AudioServiceOutOfProcess"
            ]
        )

        self.is_initialized = True
        logger.info("Shared browser initialized successfully")

    def create_audio_sink(self, session_id: str) -> tuple[str, str]:
        """
        Create a dedicated virtual audio sink for a session.

        Args:
            session_id: Unique session identifier

        Returns:
            Tuple of (sink_name, monitor_name)
        """
        self._audio_sink_counter += 1
        sink_name = f"teams_sink_{self._audio_sink_counter}"
        monitor_name = f"{sink_name}.monitor"

        try:
            logger.info(f"Creating audio sink '{sink_name}' for session {session_id}")

            # Create virtual audio sink
            cmd = [
                "pactl", "load-module", "module-null-sink",
                f"sink_name={sink_name}",
                f"sink_properties=device.description='Teams_Session_{self._audio_sink_counter}'"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                self._active_sinks[session_id] = sink_name
                logger.info(f"Audio sink created: {sink_name} -> {monitor_name}")
                return sink_name, monitor_name
            else:
                logger.error(f"Failed to create audio sink: {result.stderr}")
                raise Exception(f"Failed to create audio sink: {result.stderr}")

        except Exception as e:
            logger.error(f"Error creating audio sink: {e}")
            raise

    def remove_audio_sink(self, session_id: str):
        """
        Remove the audio sink for a session.

        Args:
            session_id: Session identifier
        """
        if session_id not in self._active_sinks:
            logger.warning(f"No audio sink found for session {session_id}")
            return

        sink_name = self._active_sinks[session_id]

        try:
            logger.info(f"Removing audio sink '{sink_name}' for session {session_id}")

            # Find and unload the module
            cmd = ["pactl", "list", "modules", "short"]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                # Find module ID by sink name
                for line in result.stdout.split('\n'):
                    if sink_name in line:
                        module_id = line.split()[0]
                        unload_cmd = ["pactl", "unload-module", module_id]
                        subprocess.run(unload_cmd, check=False)
                        logger.info(f"Unloaded audio sink module {module_id}")
                        break

            del self._active_sinks[session_id]

        except Exception as e:
            logger.error(f"Error removing audio sink: {e}")

    async def get_browser(self) -> Browser:
        """Get the shared browser instance."""
        if not self.is_initialized:
            await self._initialize()
        return self.browser

    async def cleanup(self):
        """Cleanup browser resources."""
        logger.info("Cleaning up browser manager")

        # Remove all audio sinks
        for session_id in list(self._active_sinks.keys()):
            self.remove_audio_sink(session_id)

        if self.browser:
            await self.browser.close()
            self.browser = None

        if self.playwright:
            await self.playwright.stop()
            self.playwright = None

        self.is_initialized = False
        logger.info("Browser manager cleaned up")
