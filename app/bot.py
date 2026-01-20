"""Teams bot controller using Playwright."""

import asyncio
import logging
import uuid
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page, BrowserContext, Playwright

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
        self.page: Optional[Page] = None
        self.audio_recorder: Optional[AudioRecorder] = None
        self.sink_name: Optional[str] = None
        self.monitor_name: Optional[str] = None
        self.sink_module_id: Optional[str] = None
        self._monitoring_task: Optional[asyncio.Task] = None

        logger.info(f"Initialized bot with session ID: {self.session_id}")

    def _create_audio_sink(self) -> tuple[str, str, str]:
        """Create a dedicated virtual audio sink for this session."""
        import time
        sink_name = f"teams_sink_{self.session_id[:8]}"
        monitor_name = f"{sink_name}.monitor"
        
        try:
            logger.info(f"Creating audio sink '{sink_name}' for session {self.session_id}")
            
            # Create virtual audio sink
            cmd = [
                "pactl", "load-module", "module-null-sink",
                f"sink_name={sink_name}",
                f"sink_properties=device.description='Teams_Session_{self.session_id[:8]}'"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            module_id = result.stdout.strip()
            
            # Do NOT set as default sink - let --alsa-output-device handle routing
            # Setting as default would route ALL system audio to this sink
            
            logger.info(f"Audio sink created: {sink_name} -> {monitor_name} (module {module_id})")
            return sink_name, monitor_name, module_id
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create audio sink: {e.stderr}")
            raise Exception(f"Failed to create audio sink: {e.stderr}")

    async def _setup_browser(self):
        """Setup browser with dedicated audio sink."""
        logger.info(f"Setting up browser for session {self.session_id}")

        # Create dedicated audio sink FIRST
        self.sink_name, self.monitor_name, self.sink_module_id = self._create_audio_sink()

        # Set environment variables to force this browser to use the dedicated sink
        os.environ["DISPLAY"] = f":{settings.display_number}"
        os.environ["PULSE_SINK"] = self.sink_name
        os.environ["PULSE_SOURCE"] = self.monitor_name
        
        logger.info(f"Browser will use PULSE_SINK={self.sink_name}")
        
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                f"--window-size={settings.display_width},{settings.display_height}",
                "--use-fake-device-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=AudioServiceOutOfProcess"
            ]
        )

        self.page = await self.browser.new_page(
            viewport={"width": settings.display_width, "height": settings.display_height},
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # Grant permissions for Teams domains
        context = self.page.context
        await context.grant_permissions(
            ["microphone", "camera"],
            origin="https://teams.microsoft.com"
        )
        await context.grant_permissions(
            ["microphone", "camera"],
            origin="https://teams.live.com"
        )

        await context.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})
        self.page.set_default_timeout(settings.selenium_timeout * 1000)
        logger.info(f"Browser initialized for session {self.session_id}")

    async def _join_meeting(self):
        """Join the Teams meeting."""
        logger.info(f"Joining: {self.meeting_url}")
        await self.page.goto(self.meeting_url, wait_until="domcontentloaded")
        await self.page.wait_for_timeout(3000)
        
        # Take screenshot after initial page load
        screenshot_path = Path(settings.recordings_dir) / f"{self.session_id}_initial_load.png"
        subprocess.run(["scrot", str(screenshot_path)], check=False)
        logger.info(f"Initial load screenshot: {screenshot_path}")
        logger.info(f"Current URL: {self.page.url}")

        # Click web join if available
        try:
            web_btn = self.page.locator("text=/Continue on this browser|Join on the web instead/i").first
            if await web_btn.is_visible(timeout=10000):
                logger.info("Found web join button, clicking...")
                await web_btn.click()
                await self.page.wait_for_timeout(2000)
                logger.info(f"After web join click URL: {self.page.url}")
        except Exception as e:
            screenshot_path = Path(settings.recordings_dir) / f"{self.session_id}_web_button_timeout.png"
            subprocess.run(["scrot", str(screenshot_path)], check=False)
            logger.warning(f"Web button not found - screenshot saved: {screenshot_path}")

        # Fill name
        try:
            await self.page.locator("input[data-tid='prejoin-display-name-input']").first.fill(self.display_name, timeout=30000)
        except Exception as e:
            screenshot_path = Path(settings.recordings_dir) / f"{self.session_id}_name_input_timeout.png"
            subprocess.run(["scrot", str(screenshot_path)], check=False)
            logger.error(f"Name input not found - URL: {self.page.url} - screenshot: {screenshot_path}")
            raise
        await self.page.wait_for_timeout(1000)

        # Turn off camera and mic if they're on
        for tid, name in [("toggle-video", "camera"), ("toggle-mute", "mic")]:
            toggle = self.page.locator(f"input[data-tid='{tid}'][data-cid='{tid}-true']").first
            if await toggle.is_visible(timeout=5000) and await toggle.is_checked():
                await toggle.click()
                logger.info(f"Turned off {name}")
                await self.page.wait_for_timeout(500)

        # Log selected audio devices
        try:
            speaker_label = await self.page.locator("button[data-tid='selected-speaker-display'] span.fui-StyledText").first.inner_text()
            logger.info(f"Selected speaker: {speaker_label}")
        except:
            logger.info(f"Selected speaker: (not found)")

        # Screenshot before joining (desktop screenshot)
        screenshot_path = Path(settings.recordings_dir) / f"{self.session_id}_before_join.png"
        subprocess.run(["scrot", str(screenshot_path)], check=False)
        logger.info(f"Screenshot saved: {screenshot_path}")

        # Click "Allow" text for permissions dialog if it appears
        # This must be done BEFORE clicking Join to prevent dialog from blocking
        try:
            # Click on the "Allow" text link in the permission dialog
            allow_link = self.page.get_by_text("Allow", exact=True).first
            await allow_link.wait_for(state="visible", timeout=3000)
            await allow_link.click(force=True)
            logger.info("Clicked 'Allow' for camera/mic permissions")
            
            # Wait for the dialog overlay to disappear
            dialog_overlay = self.page.locator("div.ui-dialog__overlay").first
            await dialog_overlay.wait_for(state="hidden", timeout=5000)
            logger.info("Permission dialog dismissed")
        except Exception as e:
            logger.info("No permission dialog detected or already dismissed")

        # Ensure any dialog overlays are gone before clicking Join
        try:
            dialog_overlay = self.page.locator("div.ui-dialog__overlay").first
            await dialog_overlay.wait_for(state="hidden", timeout=2000)
        except:
            pass  # No overlay, we're good

        # Join meeting
        await self.page.locator("button[data-tid='prejoin-join-button']").first.click()
        logger.info("Joining meeting...")
        await self.page.wait_for_timeout(5000)

        # Screenshot after joining (desktop screenshot)
        screenshot_path_after = Path(settings.recordings_dir) / f"{self.session_id}_after_join.png"
        subprocess.run(["scrot", str(screenshot_path_after)], check=False)
        logger.info(f"Screenshot saved: {screenshot_path_after}")
        await self.page.wait_for_timeout(5000)

        # Check if admitted
        hangup = self.page.locator("button[id='hangup-button']").first
        try:
            await hangup.wait_for(state="visible", timeout=settings.teams_join_timeout * 1000)
            self.admitted_to_meeting = True
            logger.info("Joined meeting")
        except:
            logger.info("In lobby, waiting for admission")
            self.admitted_to_meeting = False
        
        self.status = BotStatus.RECORDING

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

    async def _leave_meeting(self):
        """Leave the meeting."""
        leave_btn = self.page.locator("button[id='hangup-button']").first
        if await leave_btn.is_visible(timeout=5000):
            await leave_btn.click()
            logger.info("Left meeting")
            await self.page.wait_for_timeout(2000)

    async def _inject_monitoring_script(self):
        """Inject monitoring script into page."""
        await self.page.evaluate("""
            setInterval(() => {
                try {
                    const hangup = document.querySelector("button[id='hangup-button']");
                    const isAdmitted = hangup?.offsetParent !== null;
                    let count = -1;
                    
                    if (isAdmitted) {
                        const badge = document.querySelector("button[id='roster-button'] span[data-tid='toolbar-item-badge']");
                        const roster = document.querySelector("button[id='roster-button']");
                        count = badge?.offsetParent ? parseInt(badge.innerText) || -1 : roster?.offsetParent ? 1 : -1;
                    }
                    
                    document.body.setAttribute('data-bot-admitted', isAdmitted);
                    document.body.setAttribute('data-bot-participant-count', count);
                } catch (e) {}
            }, 1000);
        """)
        logger.info("Monitoring script injected")

    async def _monitor_participants(self):
        """Monitor participant count."""
        async def lobby_timeout():
            await asyncio.sleep(600)
            self.error_message = "Not admitted within 10 minutes"
            await self.stop()

        lobby_task = asyncio.create_task(lobby_timeout()) if not self.admitted_to_meeting else None
        logger.info("Monitoring started")
        last_count = None

        try:
            while self.status == BotStatus.RECORDING:
                admitted = await self.page.get_attribute('body', 'data-bot-admitted') == 'true'
                count = int(await self.page.get_attribute('body', 'data-bot-participant-count') or -1)
                
                if not self.admitted_to_meeting and admitted:
                    self.admitted_to_meeting = True
                    if lobby_task:
                        lobby_task.cancel()
                    logger.info("Admitted to meeting")
                
                if self.admitted_to_meeting:
                    if count != last_count:
                        logger.info(f"Participants: {count}")
                        last_count = count
                    if count == 1:
                        logger.info("Alone in meeting, leaving")
                        await self.stop()
                        break
                
                await asyncio.sleep(1)
        finally:
            if lobby_task and not lobby_task.done():
                lobby_task.cancel()

    def _start_audio_recording(self):
        """Start audio recording using the session's dedicated audio sink."""
        Path(settings.recordings_dir).mkdir(parents=True, exist_ok=True)
        self.recording_file = str(Path(settings.recordings_dir) / f"{self.session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav")
        
        # Pass the session-specific monitor name to the recorder
        self.audio_recorder = AudioRecorder(
            output_file=self.recording_file,
            duration=None,
            monitor_name=self.monitor_name
        )
        self.audio_recorder.start()
        logger.info(f"Recording from '{self.monitor_name}' to: {self.recording_file}")

    async def start(self):
        """Start the bot."""
        try:
            logger.info(f"Starting session {self.session_id}")
            self.started_at = datetime.now()
            self.status = BotStatus.JOINING

            await self._setup_browser()
            await self._join_meeting()
            await self._inject_monitoring_script()
            self._start_audio_recording()

            self.status = BotStatus.RECORDING
            self._monitoring_task = asyncio.create_task(self._monitor_participants())
            logger.info("Bot started")
        except Exception as e:
            logger.error(f"Start failed: {e}")
            self.status = BotStatus.FAILED
            self.error_message = str(e)
            await self.cleanup()
            raise

    async def stop(self):
        """Stop the bot."""
        logger.info(f"Stopping {self.session_id}")
        self.stopped_at = datetime.now()

        if self._monitoring_task and not self._monitoring_task.done():
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        if self.page and self.status == BotStatus.RECORDING:
            await self._leave_meeting()

        if self.audio_recorder:
            self.audio_recorder.stop()
            logger.info("Recording stopped")

        self.status = BotStatus.STOPPED
        await self.cleanup()

    async def cleanup(self):
        """Clean up browser and audio resources."""
        logger.info(f"Cleaning up session {self.session_id}")
        
        if self.audio_recorder:
            self.audio_recorder.stop()

        if self.page:
            try:
                await self.page.close()
            except:
                pass

        if self.browser:
            try:
                await self.browser.close()
            except:
                pass

        if self.playwright:
            try:
                await self.playwright.stop()
            except:
                pass

        # Remove the audio sink
        if self.sink_module_id:
            try:
                subprocess.run(["pactl", "unload-module", self.sink_module_id], check=False)
                logger.info(f"Audio sink removed: {self.sink_name}")
            except Exception as e:
                logger.error(f"Error removing audio sink: {e}")

        self.status = BotStatus.STOPPED
        logger.info(f"Cleanup complete for {self.session_id}")

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
