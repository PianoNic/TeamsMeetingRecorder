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
        self.admitted_to_meeting: bool = False

        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.audio_recorder: Optional[AudioRecorder] = None
        self.chromium_process: Optional[subprocess.Popen] = None
        self._stop_monitoring = None  # Event to signal monitoring thread to stop
        self._last_participant_check = 0  # Timestamp of last check
        self._check_interval = 1  # Check every 1 second

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
                # Use the specific data-tid from the Teams pre-join interface
                name_input = self.page.locator("input[data-tid='prejoin-display-name-input']").first
                name_input.fill(self.display_name)
                logger.info("Display name entered")
                self.page.wait_for_timeout(1000)
            except Exception as e:
                logger.warning(f"Could not find name input field: {e}")

            # Turn off camera and microphone before joining
            try:
                logger.info("Turning off camera and microphone")

                # Turn off camera using the switch element
                try:
                    camera_switch = self.page.locator("input[data-tid='toggle-video'][data-cid='toggle-video-true']").first
                    if camera_switch.is_visible(timeout=5000):
                        is_checked = camera_switch.is_checked()
                        logger.info(f"Camera switch checked (on): {is_checked}")
                        # If checked (true), camera is ON, so click to turn it OFF
                        if is_checked:
                            camera_switch.click()
                            logger.info("Turned camera OFF")
                            self.page.wait_for_timeout(500)
                        else:
                            logger.info("Camera is already OFF")
                    else:
                        logger.warning("Camera switch not found")
                except Exception as e:
                    logger.warning(f"Error toggling camera: {e}")

                # Mute microphone using the switch element
                try:
                    mic_switch = self.page.locator("input[data-tid='toggle-mute'][data-cid='toggle-mute-true']").first
                    if mic_switch.is_visible(timeout=5000):
                        is_checked = mic_switch.is_checked()
                        logger.info(f"Microphone switch checked (unmuted): {is_checked}")
                        # If NOT checked, microphone is already MUTED - we want it muted
                        # If checked (true), microphone is UNMUTED, so click to mute it
                        if is_checked:
                            mic_switch.click()
                            logger.info("Muted microphone")
                            self.page.wait_for_timeout(500)
                        else:
                            logger.info("Microphone is already muted")
                    else:
                        logger.warning("Microphone switch not found")
                except Exception as e:
                    logger.warning(f"Error toggling microphone: {e}")

                logger.info("Camera and microphone processing complete")
            except Exception as e:
                logger.warning(f"Error in camera/mic toggle section: {e}")

            # Click Join button
            try:
                logger.info("Looking for Join button")
                # Use the specific data-tid from the Teams pre-join interface
                join_button = self.page.locator("button[data-tid='prejoin-join-button']").first
                join_button.click()
                logger.info("Clicked Join button")
                self.page.wait_for_timeout(5000)
            except Exception as e:
                logger.error(f"Could not find Join button: {e}")
                raise

            # Check if we're in the meeting by looking for hangup button
            try:
                logger.info("Verifying meeting join")
                # Wait for hangup button to appear (indicates we're in the meeting)
                hangup_button = self.page.locator("button[id='hangup-button']").first
                hangup_button.wait_for(state="visible", timeout=settings.teams_join_timeout * 1000)
                logger.info("Successfully joined the meeting! (Hangup button visible)")
                self.admitted_to_meeting = True
                self.status = BotStatus.RECORDING

            except Exception as e:
                logger.warning(f"Could not verify meeting join (hangup button not found): {e}")
                logger.warning("Might be in lobby or waiting room - will check for admission")
                self.admitted_to_meeting = False
                self.status = BotStatus.RECORDING  # Still set to recording, as we might be in lobby

        except Exception as e:
            logger.error(f"Error joining meeting: {e}")
            raise

    def _get_participant_count(self) -> int:
        """Get the current participant count in the meeting."""
        try:
            # Try to find the badge on the roster/people button that shows participant count
            # Note: The badge only appears when there are 2+ participants
            # If no badge is visible, it means only 1 participant (the bot itself)
            count_badge = self.page.locator("button[id='roster-button'] span[data-tid='toolbar-item-badge']").first
            if count_badge.is_visible(timeout=2000):
                count_text = count_badge.inner_text().strip()
                if count_text.isdigit():
                    logger.info(f"Participant count from badge: {count_text}")
                    return int(count_text)
            
            # No badge visible - check if roster button exists (meaning we're in a meeting)
            roster_button = self.page.locator("button[id='roster-button']").first
            if roster_button.is_visible(timeout=2000):
                # If roster button exists but no badge, it means only 1 participant (the bot)
                logger.info("No participant badge visible - only bot in meeting (count: 1)")
                return 1
            
            logger.warning("Roster button not found - might not be in meeting yet")
            return -1
        except Exception as e:
            logger.warning(f"Could not get participant count: {e}")
            return -1

    def _leave_meeting(self):
        """Click the leave/hangup button to exit the meeting."""
        try:
            logger.info("Clicking leave button to exit meeting")
            # Click the hangup/leave button
            leave_button = self.page.locator("button[id='hangup-button']").first
            if leave_button.is_visible(timeout=5000):
                leave_button.click()
                logger.info("Successfully clicked leave button")
                self.page.wait_for_timeout(2000)
            else:
                logger.warning("Leave button not found")
        except Exception as e:
            logger.error(f"Error clicking leave button: {e}")

    def _inject_monitoring_script(self):
        """Inject a script into the page that monitors participant count and updates a data attribute."""
        try:
            logger.info("Injecting participant monitoring script into page")
            
            # Inject script that runs every second and updates a data attribute on the body
            monitor_script = """
            setInterval(() => {
                try {
                    // Check if admitted (hangup button exists)
                    const hangupButton = document.querySelector("button[id='hangup-button']");
                    const isAdmitted = hangupButton && hangupButton.offsetParent !== null;
                    
                    // Get participant count
                    let participantCount = -1;
                    if (isAdmitted) {
                        const badge = document.querySelector("button[id='roster-button'] span[data-tid='toolbar-item-badge']");
                        if (badge && badge.offsetParent !== null) {
                            const text = badge.innerText.trim();
                            participantCount = parseInt(text) || -1;
                        } else {
                            const rosterButton = document.querySelector("button[id='roster-button']");
                            if (rosterButton && rosterButton.offsetParent !== null) {
                                participantCount = 1;  // No badge means only bot
                            }
                        }
                    }
                    
                    // Store in body dataset for external reading
                    document.body.setAttribute('data-bot-admitted', isAdmitted ? 'true' : 'false');
                    document.body.setAttribute('data-bot-participant-count', participantCount.toString());
                } catch (e) {
                    console.error('Bot monitoring error:', e);
                }
            }, 1000);
            """
            
            self.page.evaluate(monitor_script)
            logger.info("Monitoring script injected successfully")
            
        except Exception as e:
            logger.error(f"Error injecting monitoring script: {e}")

    def _monitor_participants(self):
        """Monitor participant count by reading data attributes set by injected script."""
        import threading

        LOBBY_TIMEOUT = 600  # 10 minutes in seconds

        def leave_from_lobby():
            logger.warning("Bot was not admitted to meeting within 10 minutes. Stopping...")
            self.error_message = "Not admitted to meeting within 10 minutes"
            self.stop()

        # Start lobby timeout timer
        lobby_timer = None
        if not self.admitted_to_meeting:
            logger.info("Bot might be in lobby. Starting 10-minute admission timeout.")
            lobby_timer = threading.Timer(LOBBY_TIMEOUT, leave_from_lobby)
            lobby_timer.start()

        logger.info("Participant monitoring loop started (reading data attributes)")

        while self.status == BotStatus.RECORDING and not self._stop_monitoring.is_set():
            try:
                # Read the data attributes that the injected script updates
                # getAttribute is thread-safe for reading simple attributes
                is_admitted_str = self.page.get_attribute('body', 'data-bot-admitted')
                participant_count_str = self.page.get_attribute('body', 'data-bot-participant-count')
                
                if is_admitted_str and participant_count_str:
                    is_admitted = is_admitted_str == 'true'
                    participant_count = int(participant_count_str)
                    
                    # Check if bot has been admitted
                    if not self.admitted_to_meeting and is_admitted:
                        logger.info("Bot has been admitted to the meeting!")
                        self.admitted_to_meeting = True
                        # Cancel lobby timeout
                        if lobby_timer is not None:
                            lobby_timer.cancel()
                            lobby_timer = None

                    # Monitor participant count if admitted
                    if self.admitted_to_meeting:
                        logger.info(f"Current participant count: {participant_count}")

                        if participant_count == 1:
                            # Only bot is in the meeting - leave immediately
                            logger.info("Bot is alone in meeting. Leaving immediately...")
                            self.stop()
                            break
                        elif participant_count > 1:
                            logger.info(f"Other participants present ({participant_count} total)")
                    else:
                        logger.info("Not admitted yet, waiting...")
                
                # Wait 1 second or until stop is signaled
                self._stop_monitoring.wait(timeout=1)

            except Exception as e:
                logger.error(f"Error monitoring participants: {e}")
                self._stop_monitoring.wait(timeout=1)

        # Cleanup timers if monitoring stops
        logger.info("Participant monitoring loop ended")
        if lobby_timer is not None:
            lobby_timer.cancel()

    def _start_audio_recording(self):
        """Start recording audio from the virtual sink."""
        try:
            logger.info("Starting audio recording")
            
            # Create output file path
            from pathlib import Path
            recordings_dir = Path(settings.recordings_dir)
            recordings_dir.mkdir(parents=True, exist_ok=True)
            
            output_file = recordings_dir / f"{self.session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
            self.recording_file = str(output_file)
            
            # Initialize AudioRecorder with correct parameters
            self.audio_recorder = AudioRecorder(
                output_file=self.recording_file,
                duration=None  # Unlimited duration
            )
            self.audio_recorder.start()
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
            self._stop_monitoring = threading.Event()

            # Setup browser
            self._setup_browser()

            # Join meeting
            self._join_meeting()

            # Inject monitoring script into the page
            self._inject_monitoring_script()

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

        # Signal monitoring thread to stop
        if self._stop_monitoring:
            self._stop_monitoring.set()

        # Leave the meeting first
        if self.page and self.status == BotStatus.RECORDING:
            try:
                self._leave_meeting()
            except Exception as e:
                logger.error(f"Error leaving meeting: {e}")

        # Stop audio recording
        if self.audio_recorder:
            try:
                self.audio_recorder.stop()
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
