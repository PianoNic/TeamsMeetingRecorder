"""Teams bot controller using Selenium WebDriver."""

import time
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from pyvirtualdisplay import Display

from app.config import settings
from app.models import BotStatus
from app.recorder import AudioRecorder

logger = logging.getLogger(__name__)


class TeamsBot:
    """Bot that joins Teams meetings and records audio."""

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

        self.driver: Optional[webdriver.Chrome] = None
        self.display: Optional[Display] = None
        self.audio_recorder: Optional[AudioRecorder] = None

        logger.info(f"Initialized bot with session ID: {self.session_id}")

    def _setup_display(self):
        """Setup virtual display for headless operation."""
        try:
            logger.info("Setting up virtual display")
            self.display = Display(
                visible=False,
                size=(settings.display_width, settings.display_height),
                backend="xvfb"
            )
            self.display.start()
            logger.info(f"Virtual display started on DISPLAY={self.display.display}")
        except Exception as e:
            logger.error(f"Error setting up virtual display: {e}")
            raise

    def _setup_driver(self):
        """Setup Chrome WebDriver with appropriate options."""
        try:
            logger.info("Setting up Chrome WebDriver")

            chrome_options = Options()
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--disable-software-rasterizer")
            chrome_options.add_argument(f"--window-size={settings.display_width},{settings.display_height}")

            # Allow microphone and camera access
            chrome_options.add_argument("--use-fake-ui-for-media-stream")
            chrome_options.add_argument("--use-fake-device-for-media-stream")

            # Use virtual audio device
            chrome_options.add_argument(f"--alsa-output-device={settings.pulseaudio_sink_name}")

            # Additional stability options
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)

            # Preferences
            prefs = {
                "profile.default_content_setting_values.media_stream_mic": 1,
                "profile.default_content_setting_values.media_stream_camera": 1,
                "profile.default_content_setting_values.notifications": 2
            }
            chrome_options.add_experimental_option("prefs", prefs)

            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.implicitly_wait(settings.implicit_wait)
            self.driver.set_page_load_timeout(settings.page_load_timeout)

            logger.info("Chrome WebDriver initialized successfully")

        except Exception as e:
            logger.error(f"Error setting up WebDriver: {e}")
            raise

    def _join_meeting(self):
        """Join the Teams meeting."""
        try:
            logger.info(f"Navigating to meeting URL: {self.meeting_url}")
            self.driver.get(self.meeting_url)

            # Wait for page to load
            time.sleep(3)

            # Try to join via browser (without app)
            try:
                logger.info("Looking for 'Join on the web instead' button")
                web_join_button = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Continue on this browser') or contains(text(), 'Join on the web instead')]"))
                )
                web_join_button.click()
                logger.info("Clicked 'Join on the web' button")
                time.sleep(2)
            except TimeoutException:
                logger.info("No 'Join on the web' button found, might already be on web version")

            # Enter display name
            try:
                logger.info(f"Entering display name: {self.display_name}")
                name_input = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'][placeholder*='name' i], input[id*='name' i]"))
                )
                name_input.clear()
                name_input.send_keys(self.display_name)
                logger.info("Display name entered")
                time.sleep(1)
            except TimeoutException:
                logger.warning("Could not find name input field")

            # Turn off camera and microphone before joining
            try:
                logger.info("Turning off camera and microphone")
                # Find and click camera toggle
                camera_button = self.driver.find_element(By.CSS_SELECTOR, "button[data-tid='toggle-video'], button[aria-label*='camera' i]")
                if "on" in camera_button.get_attribute("aria-pressed").lower() or "true" in camera_button.get_attribute("aria-pressed").lower():
                    camera_button.click()
                    time.sleep(0.5)

                # Find and click microphone toggle
                mic_button = self.driver.find_element(By.CSS_SELECTOR, "button[data-tid='toggle-mute'], button[aria-label*='microphone' i], button[aria-label*='mute' i]")
                if "on" in mic_button.get_attribute("aria-pressed").lower() or "false" in mic_button.get_attribute("aria-pressed").lower():
                    mic_button.click()
                    time.sleep(0.5)

                logger.info("Camera and microphone turned off")
            except NoSuchElementException:
                logger.warning("Could not find camera/mic toggle buttons")

            # Click Join button
            try:
                logger.info("Looking for Join button")
                join_button = WebDriverWait(self.driver, 15).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Join') or contains(text(), 'Beitreten')]"))
                )
                join_button.click()
                logger.info("Clicked Join button")
                time.sleep(5)
            except TimeoutException:
                logger.error("Could not find Join button")
                raise

            # Check if we're in the meeting
            try:
                logger.info("Verifying meeting join")
                WebDriverWait(self.driver, settings.teams_join_timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div[class*='calling'], div[class*='meeting'], button[aria-label*='leave' i]"))
                )
                logger.info("Successfully joined the meeting!")
                self.status = BotStatus.RECORDING

            except TimeoutException:
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

            # Setup virtual display
            if not settings.browser_headless:
                self._setup_display()

            # Setup WebDriver
            self._setup_driver()

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

            # Leave meeting and close browser
            if self.driver:
                try:
                    logger.info("Closing browser")
                    self.driver.quit()
                except Exception as e:
                    logger.warning(f"Error closing browser: {e}")

            # Stop virtual display
            if self.display:
                try:
                    logger.info("Stopping virtual display")
                    self.display.stop()
                except Exception as e:
                    logger.warning(f"Error stopping display: {e}")

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
