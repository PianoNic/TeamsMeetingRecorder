"""Teams bot controller using Playwright."""

import time
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext, Playwright

from app.config import settings
from app.models import BotStatus
from app.recorder import AudioRecorder

logger = logging.getLogger(__name__)


class TeamsBot:
    """Bot that joins Teams meetings and records audio using Playwright."""

    def __init__(
        self,
        meeting_url: str,
        display_name: str,
        record_audio: bool = True,
        max_duration_minutes: Optional[int] = None
    ):
        """
        Initialize the Teams bot.

        Args:
            meeting_url: Microsoft Teams meeting URL
            display_name: Display name to use in the meeting
            record_audio: Whether to record audio
            max_duration_minutes: Maximum recording duration in minutes
        """
        self.session_id = str(uuid.uuid4())
        self.meeting_url = meeting_url
        self.display_name = display_name
        self.record_audio = record_audio
        self.max_duration_minutes = max_duration_minutes

        self.status = BotStatus.IDLE
        self.started_at: Optional[datetime] = None
        self.stopped_at: Optional[datetime] = None
        self.recording_file: Optional[str] = None
        self.error_message: Optional[str] = None

        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.audio_recorder: Optional[AudioRecorder] = None

        logger.info(f"Initialized bot with session ID: {self.session_id}")

    def _setup_browser(self):
        """Setup Playwright browser with appropriate options."""
        try:
            logger.info("Setting up Playwright Chromium browser")

            # Launch Playwright
            self.playwright = sync_playwright().start()

            # Browser launch arguments (2026 best practices)
            launch_args = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                f"--window-size={settings.display_width},{settings.display_height}",
                # Allow media access
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                # Use virtual audio device
                f"--alsa-output-device={settings.pulseaudio_sink_name}",
                # Additional stability
                "--disable-blink-features=AutomationControlled",
            ]

            # Launch browser with new headless mode (2026 standard)
            # Uses chromium channel for optimal performance
            self.browser = self.playwright.chromium.launch(
                headless=settings.browser_headless,
                args=launch_args,
                channel="chromium"  # Use chromium for new headless mode
            )

            # Create browser context with permissions (Playwright's efficient context model)
            self.context = self.browser.new_context(
                viewport={
                    "width": settings.display_width,
                    "height": settings.display_height
                },
                # Grant media permissions
                permissions=["microphone", "camera"],
                # Additional context options
                ignore_https_errors=True,
                java_script_enabled=True,
                # Set user agent to avoid detection
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

            # Set extra HTTP headers
            self.context.set_extra_http_headers({
                "Accept-Language": "en-US,en;q=0.9",
            })

            # Create new page
            self.page = self.context.new_page()

            # Set default timeout
            self.page.set_default_timeout(settings.selenium_timeout * 1000)

            logger.info("Playwright browser initialized successfully")

        except Exception as e:
            logger.error(f"Error setting up browser: {e}")
            raise

    def _join_meeting(self):
        """Join the Teams meeting using Playwright's auto-waiting."""
        try:
            logger.info(f"Navigating to meeting URL: {self.meeting_url}")
            self.page.goto(self.meeting_url, wait_until="domcontentloaded")

            # Wait for page to load
            self.page.wait_for_timeout(3000)

            # Try to join via browser (without app)
            try:
                logger.info("Looking for 'Join on the web instead' button")
                # Playwright auto-waits for element - no explicit waits needed!
                web_join_button = self.page.locator("text=/Continue on this browser|Join on the web instead/i").first
                if web_join_button.is_visible(timeout=10000):
                    web_join_button.click()
                    logger.info("Clicked 'Join on the web' button")
                    self.page.wait_for_timeout(2000)
            except Exception:
                logger.info("No 'Join on the web' button found, might already be on web version")

            # Enter display name
            try:
                logger.info(f"Entering display name: {self.display_name}")
                # Playwright's auto-waiting handles element readiness
                name_input = self.page.locator("input[type='text'][placeholder*='name' i], input[id*='name' i]").first
                name_input.fill(self.display_name)
                logger.info("Display name entered")
                self.page.wait_for_timeout(1000)
            except Exception:
                logger.warning("Could not find name input field")

            # Turn off camera and microphone before joining
            try:
                logger.info("Turning off camera and microphone")

                # Find and click camera toggle
                camera_button = self.page.locator("button[data-tid='toggle-video'], button[aria-label*='camera' i]").first
                if camera_button.is_visible(timeout=5000):
                    aria_pressed = camera_button.get_attribute("aria-pressed")
                    if aria_pressed and ("on" in aria_pressed.lower() or "true" in aria_pressed.lower()):
                        camera_button.click()
                        self.page.wait_for_timeout(500)

                # Find and click microphone toggle
                mic_button = self.page.locator("button[data-tid='toggle-mute'], button[aria-label*='microphone' i], button[aria-label*='mute' i]").first
                if mic_button.is_visible(timeout=5000):
                    aria_pressed = mic_button.get_attribute("aria-pressed")
                    if aria_pressed and ("on" in aria_pressed.lower() or "false" in aria_pressed.lower()):
                        mic_button.click()
                        self.page.wait_for_timeout(500)

                logger.info("Camera and microphone turned off")
            except Exception:
                logger.warning("Could not find camera/mic toggle buttons")

            # Click Join button
            try:
                logger.info("Looking for Join button")
                # Playwright's auto-waiting is superior to Selenium's explicit waits
                join_button = self.page.locator("button:has-text('Join'), button:has-text('Beitreten')").first
                join_button.click()
                logger.info("Clicked Join button")
                self.page.wait_for_timeout(5000)
            except Exception:
                logger.error("Could not find Join button")
                raise

            # Check if we're in the meeting
            try:
                logger.info("Verifying meeting join")
                # Wait for meeting UI elements
                self.page.locator("div[class*='calling'], div[class*='meeting'], button[aria-label*='leave' i]").first.wait_for(
                    timeout=settings.teams_join_timeout * 1000
                )
                logger.info("Successfully joined the meeting!")
                self.status = BotStatus.RECORDING

            except Exception:
                logger.warning("Could not verify meeting join, might be in lobby")
                self.status = BotStatus.RECORDING  # Still set to recording, as we might be in lobby

        except Exception as e:
            logger.error(f"Error joining meeting: {e}", exc_info=True)
            self.status = BotStatus.ERROR
            self.error_message = str(e)
            raise

    def start(self):
        """Start the bot and begin recording."""
        try:
            logger.info(f"Starting bot session {self.session_id}")
            self.started_at = datetime.utcnow()
            self.status = BotStatus.JOINING

            # Setup browser (Playwright handles displays internally)
            self._setup_browser()

            # Join meeting
            self._join_meeting()

            # Start audio recording if enabled
            if self.record_audio:
                logger.info("Starting audio recording")
                self.recording_file = str(
                    Path(settings.recordings_dir) / f"{self.session_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.wav"
                )
                self.audio_recorder = AudioRecorder(
                    output_file=self.recording_file,
                    duration=self.max_duration_minutes * 60 if self.max_duration_minutes else None
                )
                self.audio_recorder.start()
                logger.info(f"Recording started, saving to: {self.recording_file}")

            # Keep the bot running
            if self.max_duration_minutes:
                logger.info(f"Bot will run for {self.max_duration_minutes} minutes")
                time.sleep(self.max_duration_minutes * 60)
                self.stop()
            else:
                logger.info("Bot running indefinitely until stopped")
                # Keep running (will be stopped by stop() call)
                while self.status == BotStatus.RECORDING:
                    time.sleep(5)

        except Exception as e:
            logger.error(f"Error in bot execution: {e}", exc_info=True)
            self.status = BotStatus.ERROR
            self.error_message = str(e)
            self.stop()

    def stop(self):
        """Stop the bot and cleanup resources."""
        try:
            logger.info(f"Stopping bot session {self.session_id}")
            self.status = BotStatus.LEAVING
            self.stopped_at = datetime.utcnow()

            # Stop audio recording
            if self.audio_recorder:
                logger.info("Stopping audio recording")
                self.audio_recorder.stop()

            # Close browser and cleanup Playwright
            if self.page:
                try:
                    logger.info("Closing page")
                    self.page.close()
                except Exception as e:
                    logger.warning(f"Error closing page: {e}")

            if self.context:
                try:
                    logger.info("Closing browser context")
                    self.context.close()
                except Exception as e:
                    logger.warning(f"Error closing context: {e}")

            if self.browser:
                try:
                    logger.info("Closing browser")
                    self.browser.close()
                except Exception as e:
                    logger.warning(f"Error closing browser: {e}")

            if self.playwright:
                try:
                    logger.info("Stopping Playwright")
                    self.playwright.stop()
                except Exception as e:
                    logger.warning(f"Error stopping Playwright: {e}")

            self.status = BotStatus.STOPPED
            logger.info(f"Bot session {self.session_id} stopped successfully")

        except Exception as e:
            logger.error(f"Error stopping bot: {e}", exc_info=True)
            self.status = BotStatus.ERROR
            self.error_message = str(e)

    def get_uptime(self) -> Optional[float]:
        """Get the uptime of the bot in seconds."""
        if not self.started_at:
            return None
        end_time = self.stopped_at or datetime.utcnow()
        return (end_time - self.started_at).total_seconds()

    def get_recording_duration(self) -> Optional[float]:
        """Get the recording duration in seconds."""
        if self.audio_recorder:
            return self.audio_recorder.get_duration()
        return None
