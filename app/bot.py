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
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.audio_recorder: Optional[AudioRecorder] = None
        self.chromium_process: Optional[subprocess.Popen] = None
        self._monitoring_task: Optional[asyncio.Task] = None

        logger.info(f"Initialized bot with session ID: {self.session_id}")

    async def _setup_browser(self):
        """Setup Playwright browser with appropriate options."""
        logger.info("Setting up Playwright Chromium browser")
        os.environ["DISPLAY"] = f":{settings.display_number}"

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox", "--disable-dev-shm-usage",
                f"--window-size={settings.display_width},{settings.display_height}",
                "--use-fake-device-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
                f"--alsa-output-device={settings.pulseaudio_sink_name}",
                f"--alsa-input-device={settings.pulseaudio_monitor_name}",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=AudioServiceOutOfProcess"
            ]
        )
        
        self.context = await self.browser.new_context(
            viewport={"width": settings.display_width, "height": settings.display_height},
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # Grant permissions for all Teams domains
        await self.context.grant_permissions(
            ["microphone", "camera"],
            origin="https://teams.microsoft.com"
        )
        
        await self.context.grant_permissions(
            ["microphone", "camera"],
            origin="https://teams.live.com"
        )
      
        await self.context.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})
        self.page = await self.context.new_page()
        self.page.set_default_timeout(settings.selenium_timeout * 1000)
        logger.info("Browser initialized")

    async def _join_meeting(self):
        """Join the Teams meeting."""
        logger.info(f"Joining: {self.meeting_url}")
        await self.page.goto(self.meeting_url, wait_until="domcontentloaded")
        await self.page.wait_for_timeout(3000)

        # Click web join if available
        try:
            web_btn = self.page.locator("text=/Continue on this browser|Join on the web instead/i").first
            if await web_btn.is_visible(timeout=10000):
                await web_btn.click()
                await self.page.wait_for_timeout(2000)
        except Exception as e:
            screenshot_path = Path(settings.recordings_dir) / f"{self.session_id}_web_button_timeout.png"
            subprocess.run(["scrot", str(screenshot_path)], check=False)
            logger.warning(f"Web button timeout - screenshot saved: {screenshot_path}")

        # Fill name
        await self.page.locator("input[data-tid='prejoin-display-name-input']").first.fill(self.display_name)
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
            mic_label = await self.page.locator("button[data-tid='selected-microphone-display'] span.fui-StyledText").first.inner_text()
            logger.info(f"Selected microphone: {mic_label}")
        except:
            logger.info(f"Selected microphone: None")
        
        try:
            speaker_label = await self.page.locator("button[data-tid='selected-speaker-display'] span.fui-StyledText").first.inner_text()
            logger.info(f"Selected speaker: {speaker_label}")
        except:
            logger.info(f"Selected speaker: None")

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
        """Start audio recording."""
        Path(settings.recordings_dir).mkdir(parents=True, exist_ok=True)
        self.recording_file = str(Path(settings.recordings_dir) / f"{self.session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav")
        self.audio_recorder = AudioRecorder(output_file=self.recording_file, duration=None)
        self.audio_recorder.start()
        logger.info(f"Recording: {self.recording_file}")

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
        """Clean up resources."""
        for resource in [self.page, self.context, self.browser, self.playwright]:
            if resource:
                await resource.close() if hasattr(resource, 'close') else await resource.stop()
        logger.info("Cleanup complete")

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
