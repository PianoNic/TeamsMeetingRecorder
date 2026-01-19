"""Teams bot controller using Playwright."""

import time
import logging
import uuid
import os
import subprocess
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
        display_name: str
    ):
        """
        Initialize the Teams bot.

        Args:
            meeting_url: Microsoft Teams meeting URL
            display_name: Display name to use in the meeting
        """
        self.session_id = str(uuid.uuid4())
        self.meeting_url = meeting_url
        self.display_name = display_name

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
        self.chromium_process: Optional[subprocess.Popen] = None

        logger.info(f"Initialized bot with session ID: {self.session_id}")

    def _setup_browser(self):
        """Setup Playwright browser with appropriate options."""
        try:
            logger.info("Setting up Playwright Chromium browser")

            # Set DISPLAY environment variable for Xvfb
            display_num = f":{settings.display_number}"
            os.environ["DISPLAY"] = display_num
            logger.info(f"Set DISPLAY to {display_num}")

            # Launch Playwright
            self.playwright = sync_playwright().start()

            # Browser launch arguments for visible window
            launch_args = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                f"--window-size={settings.display_width},{settings.display_height}",
                # Allow media access but keep muted
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
                # Mute audio output to prevent beeping
                "--mute-audio",
                # Use virtual audio device
                f"--alsa-output-device={settings.pulseaudio_sink_name}",
                # Additional stability
                "--disable-blink-features=AutomationControlled",
                "--disable-features=AudioServiceOutOfProcess",
            ]

            # Launch browser with headless=False for visible window
            logger.info("Launching browser with headless=False")
            self.browser = self.playwright.chromium.launch(
                headless=False,
                args=launch_args
            )

            # Create browser context
            self.context = self.browser.new_context(
                viewport={
                    "width": settings.display_width,
                    "height": settings.display_height
                },
                permissions=["microphone", "camera"],
                ignore_https_errors=True,
                java_script_enabled=True,
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

                # Find and click camera toggle - turn OFF if currently ON
                # Based on proven working implementations - use nested selector for button
                camera_button = self.page.locator("toggle-button[data-tid='toggle-video'] > div > button").first
                if camera_button.is_visible(timeout=5000):
                    aria_pressed = camera_button.get_attribute("aria-pressed")
                    logger.info(f"Camera button aria-pressed: {aria_pressed}")
                    # If aria-pressed="true", camera is ON, so click to turn it OFF
                    if aria_pressed and aria_pressed.lower() == "true":
                        camera_button.click()
                        logger.info("Turned camera OFF")
                        self.page.wait_for_timeout(500)
                    else:
                        logger.info("Camera is already OFF")
                else:
                    logger.warning("Camera button not found")

                # Find and click microphone toggle - MUTE if currently UNMUTED
                # Based on proven working implementations
                mic_button = self.page.locator("toggle-button[data-tid='toggle-mute'] > div > button").first
                if mic_button.is_visible(timeout=5000):
                    aria_pressed = mic_button.get_attribute("aria-pressed")
                    logger.info(f"Microphone button aria-pressed: {aria_pressed}")
                    # If aria-pressed="true", microphone is ON (unmuted), so click to mute it
                    if aria_pressed and aria_pressed.lower() == "true":
                        mic_button.click()
                        logger.info("Muted microphone")
                        self.page.wait_for_timeout(500)
                    else:
                        logger.info("Microphone is already muted")
                else:
                    logger.warning("Microphone button not found")

                logger.info("Camera and microphone processing complete")
            except Exception as e:
                logger.warning(f"Could not find camera/mic toggle buttons: {e}")

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
            logger.error(f"Error joining meeting: {e}")
            raise

    def _get_participant_count(self) -> int:
        """Get the current participant count in the meeting."""
        try:
            # Try to find the roster button that shows participant count
            count_elem = self.page.locator("span[data-tid='roster-button-tile']").first
            if count_elem.is_visible(timeout=2000):
                count_text = count_elem.inner_text().strip()
                if count_text.isdigit():
                    return int(count_text)
            return -1
        except Exception as e:
            logger.debug(f"Could not get participant count: {e}")
            return -1

    def _monitor_participants(self):
        """Monitor participant count and leave if alone for 5 minutes."""
        import threading

        low_member_timer = None
        LOW_MEMBER_WAIT_TIME = 300  # 5 minutes in seconds

        def leave_after_delay():
            logger.info("5 minutes elapsed with only bot in meeting. Leaving...")
            self.stop()

        while self.status == BotStatus.RECORDING:
            try:
                participant_count = self._get_participant_count()

                if participant_count > 1:
                    # Other participants present, cancel timer if active
                    if low_member_timer is not None:
                        logger.info(f"Participant count increased to {participant_count}. Cancelling auto-leave timer.")
                        low_member_timer.cancel()
                        low_member_timer = None
                elif participant_count == 1:
                    # Only bot is in the meeting
                    if low_member_timer is None:
                        logger.info("Bot is alone in meeting. Starting 5-minute timer before auto-leave.")
                        low_member_timer = threading.Timer(LOW_MEMBER_WAIT_TIME, leave_after_delay)
                        low_member_timer.start()

                time.sleep(30)  # Check every 30 seconds

            except Exception as e:
                logger.error(f"Error monitoring participants: {e}")
                time.sleep(30)

    def _start_audio_recording(self):
        """Start recording audio from the virtual sink."""
        try:
            logger.info("Starting audio recording")
            self.audio_recorder = AudioRecorder(
                sink_name=settings.pulseaudio_monitor_name,
                output_dir=settings.recordings_dir,
                session_id=self.session_id
            )
            self.audio_recorder.start_recording()
            self.recording_file = self.audio_recorder.output_file
            logger.info(f"Audio recording started: {self.recording_file}")

        except Exception as e:
            logger.error(f"Error starting audio recording: {e}")
            self.error_message = f"Failed to start audio recording: {e}"

    def start(self):
        """Start the bot session."""
        import threading

        try:
            logger.info(f"Starting bot session {self.session_id}")
            self.started_at = datetime.now()
            self.status = BotStatus.JOINING

            # Setup browser
            self._setup_browser()

            # Join meeting
            self._join_meeting()

            # Start audio recording
            self._start_audio_recording()

            self.status = BotStatus.RECORDING
            logger.info("Bot session started successfully")

            # Start participant monitoring in background thread
            monitor_thread = threading.Thread(target=self._monitor_participants, daemon=True)
            monitor_thread.start()
            logger.info("Participant monitoring started")

        except Exception as e:
            logger.error(f"Error starting bot session: {e}")
            self.status = BotStatus.FAILED
            self.error_message = str(e)
            self.cleanup()
            raise

    def stop(self):
        """Stop the bot session."""
        logger.info(f"Stopping bot session {self.session_id}")
        self.stopped_at = datetime.now()

        # Stop audio recording
        if self.audio_recorder:
            try:
                self.audio_recorder.stop_recording()
                logger.info("Audio recording stopped")
            except Exception as e:
                logger.error(f"Error stopping audio recording: {e}")

        self.status = BotStatus.STOPPED
        self.cleanup()

    def cleanup(self):
        """Clean up browser resources."""
        try:
            if self.page:
                self.page.close()
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            logger.info("Browser resources cleaned up")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def get_uptime(self) -> Optional[float]:
        """Get the uptime in seconds since bot started."""
        if self.started_at is None:
            return None
        if self.stopped_at is not None:
            return (self.stopped_at - self.started_at).total_seconds()
        return (datetime.now() - self.started_at).total_seconds()

    def get_recording_duration(self) -> Optional[float]:
        """Get the recording duration in seconds."""
        return self.get_uptime()  # Same as uptime for now
