"""Teams bot controller using Playwright."""

import asyncio
import logging
import uuid
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from playwright.async_api import async_playwright, Browser, Page, Playwright

from app.config import settings, DISPLAY_NUMBER, DISPLAY_WIDTH, DISPLAY_HEIGHT, BROWSER_TIMEOUT, RECORDINGS_DIR
from app.models import BotStatus
from app.recorder import AudioRecorder
from app.storage import get_storage
from app.webhook import send_webhook, WebhookPayload

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
        self.recording_started_at: Optional[datetime] = None
        self.stopped_at: Optional[datetime] = None
        self.recording_file: Optional[str] = None
        self.storage_path: Optional[str] = None
        self.error_message: Optional[str] = None

        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.audio_recorder: Optional[AudioRecorder] = None
        self.sink_name: Optional[str] = None
        self.monitor_name: Optional[str] = None
        self.sink_module_id: Optional[str] = None
        self._monitoring_task: Optional[asyncio.Task] = None

        # Invoked once with this session's id when the bot reaches a terminal
        # state, so the API can retire it from the active session list.
        self.on_stop: Optional[Callable[[str], None]] = None
        self._on_stop_fired = False

        logger.info(f"Initialized bot with session ID: {self.session_id}")

    def _create_audio_sink(self) -> tuple[str, str, str]:
        """Create a dedicated virtual audio sink for this session."""
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

        # Pin the sink on the launched process only. Mutating os.environ here would
        # race: with two sessions starting at once the second overwrites the value
        # before the first chromium has forked, and both meetings land in one sink.
        browser_env = {
            **os.environ,
            "DISPLAY": f":{DISPLAY_NUMBER}",
            "PULSE_SINK": self.sink_name,
            "PULSE_SOURCE": self.monitor_name,
        }

        logger.info(f"Browser will use PULSE_SINK={self.sink_name}")

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=False,
            env=browser_env,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                f"--window-size={DISPLAY_WIDTH},{DISPLAY_HEIGHT}",
                "--use-fake-device-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=AudioServiceOutOfProcess"
            ]
        )

        self.page = await self.browser.new_page(
            viewport={"width": DISPLAY_WIDTH, "height": DISPLAY_HEIGHT},
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
        self.page.set_default_timeout(BROWSER_TIMEOUT * 1000)
        logger.info(f"Browser initialized for session {self.session_id}")

    async def _join_meeting(self):
        """Join the Teams meeting."""
        logger.info(f"Joining: {self.meeting_url}")
        await self.page.goto(self.meeting_url, wait_until="domcontentloaded")

        # # Check for App Opening
        # web_btn = self.page.locator("text=/Continue on this browser|Join on the web instead/i").first
        # if await web_btn.is_visible():
        #     logger.info("Found web join button, clicking...")
        #     await web_btn.click()

        # Fill name
        try:
            name_input = self.page.locator("input[data-tid='prejoin-display-name-input']").first
            await name_input.wait_for(state="visible")
            await name_input.fill(self.display_name)
        except Exception as e:
            logger.error(f"Couldn't fill in Username: {e}")

        # Turn off camera and mic if they're on
        try:
            for tid, name in [("toggle-video", "camera"), ("toggle-mute", "mic")]:
                toggle = self.page.locator(f"input[data-tid='{tid}'][data-cid='{tid}-true']").first
                if await toggle.is_visible() and await toggle.is_checked():
                    await toggle.click()
                    logger.info(f"Turned off {name}")
        except Exception as e:
            logger.error(f"Problem toggling camera or mic: {e}")

        # Log selected audio device. Diagnostics only, so it gets a short explicit
        # timeout - the page default is BROWSER_TIMEOUT (24 min), long enough to
        # miss the meeting if Teams ever renames this selector.
        try:
            speaker_label = await self.page.locator(
                "button[data-tid='selected-speaker-display'] span.fui-StyledText"
            ).first.inner_text(timeout=5000)
            logger.info(f"Selected speaker: {speaker_label}")
        except Exception as e:
            logger.warning(f"Could not read selected speaker: {e}")

        # Join meeting
        try:
            await self.page.locator("button[data-tid='prejoin-join-button']").first.click()
            logger.info("Request Joining meeting...")
        except Exception as e:
            logger.error(f"Problem clicking on join: {e}")

        # Check if admitted
        try:
            hangup = self.page.locator("button[id='hangup-button']").first
            timeout_ms = settings.teams_wait_for_lobby * 60 * 1000

            await hangup.wait_for(state="visible", timeout=timeout_ms)
            logger.info("Joined meeting")
        except Exception as e:
            logger.info(f"Not admitted within {settings.teams_wait_for_lobby} minute")
            await self.stop()
            return  # Do not continue to start recording; sink is already removed in cleanup

    async def _leave_meeting(self):
        """Leave the meeting."""
        leave_btn = self.page.locator("button[id='hangup-button']").first
        if await leave_btn.is_visible(timeout=5000):
            await leave_btn.click()
            logger.info("Left meeting")
            await self.page.wait_for_timeout(2000)

    @staticmethod
    def _parse_participant_count(badge_text: str) -> int:
        """Read a participant count off the roster badge.

        Teams renders overflow counts as '99+' and may group thousands, so strip
        everything that is not a digit rather than trusting int() with the raw text.
        """
        digits = "".join(c for c in badge_text if c.isdigit())
        return int(digits) if digits else 0

    # Consecutive one-second polls that must agree before the bot acts on them.
    # A single reading is never enough: the toolbar re-renders, and the roster
    # badge is missing entirely for the first moments after being admitted.
    ALONE_POLLS_BEFORE_LEAVING = 5

    # Every Playwright call in the monitor uses this instead of the page default
    # (BROWSER_TIMEOUT, 24 minutes). A wedged page must not stall the monitor:
    # that has been observed leaving a bot recording with no supervision at all.
    MONITOR_QUERY_TIMEOUT_MS = 5000

    async def _still_in_meeting(self) -> Optional[bool]:
        """Is the bot still in the call? None when it cannot be determined.

        The hangup button is the reliable signal. Participant counts are not:
        Teams restricts the roster for unverified anonymous guests, so the bot
        frequently sees only itself listed and the toolbar badge is often never
        rendered at all.
        """
        try:
            hangup = self.page.locator("button[id='hangup-button']").first
            return await hangup.is_visible(timeout=self.MONITOR_QUERY_TIMEOUT_MS)
        except Exception as e:
            logger.warning(f"Could not read call state: {e}")
            return None

    # Anonymous joins usually land in Teams' "light meetings" client, which has no
    # participant badge at all - it shows this instead while the bot is the only
    # one left. The bot forces Accept-Language en-US, so the string is stable.
    ALONE_TEXT = "Waiting for others to join"

    async def _read_participant_count(self) -> Optional[int]:
        """Participants reported by the toolbar badge, or None when unavailable.

        Only present in the full web client; the light client has no badge.
        """
        try:
            badge = self.page.locator("button[id='roster-button'] span[data-tid='toolbar-item-badge']").first
            if await badge.is_visible(timeout=self.MONITOR_QUERY_TIMEOUT_MS):
                raw = await badge.inner_text(timeout=self.MONITOR_QUERY_TIMEOUT_MS)
                return self._parse_participant_count(raw)
        except Exception as e:
            logger.debug(f"Roster badge unreadable: {e}")
        return None

    async def _looks_alone(self) -> Optional[bool]:
        """Is the bot the only one left? None when it cannot be determined."""
        try:
            waiting = self.page.get_by_text(self.ALONE_TEXT, exact=False).first
            if await waiting.is_visible(timeout=self.MONITOR_QUERY_TIMEOUT_MS):
                return True
            text_readable = True
        except Exception as e:
            logger.debug(f"Alone-text unreadable: {e}")
            text_readable = False

        count = await self._read_participant_count()
        if count is not None:
            return count == 0

        # The light client reliably shows ALONE_TEXT when alone, so a successful
        # read with no such text means company is present.
        return False if text_readable else None

    async def _monitor_presence(self):
        """Stop recording once the meeting is over or the bot is left alone."""
        logger.info("Monitoring call state")
        gone_polls = 0
        alone_polls = 0
        polls = 0

        while self.status == BotStatus.RECORDING:
            polls += 1

            # Hard cap, independent of anything the Teams UI tells us. Everything
            # below reads the page, so a UI change could stop the bot ever leaving.
            # Measured from the start of the recording, not the start of the
            # session - otherwise a long lobby wait eats into the cap.
            if settings.max_recording_minutes > 0 and self.recording_started_at:
                elapsed = (datetime.now() - self.recording_started_at).total_seconds()
                if elapsed >= settings.max_recording_minutes * 60:
                    logger.warning(
                        f"Reached max recording duration of {settings.max_recording_minutes} minutes, stopping"
                    )
                    await self.stop()
                    break

            # Catches the meeting being ended for us, or the bot being removed.
            in_call = await self._still_in_meeting()
            if in_call is False:
                gone_polls += 1
                if gone_polls >= self.ALONE_POLLS_BEFORE_LEAVING:
                    logger.info("No longer in the call, stopping")
                    await self.stop()
                    break
            else:
                gone_polls = 0

            # Secondary: Teams leaves a lone participant sitting in the meeting
            # rather than ejecting them, so the call-state check above never
            # fires for "everyone else hung up". Unknown is not alone.
            alone = await self._looks_alone()
            if alone is True:
                alone_polls += 1
                if alone_polls >= self.ALONE_POLLS_BEFORE_LEAVING:
                    logger.info("Alone in meeting or kicked, leaving")
                    await self.stop()
                    break
            elif alone is False:
                alone_polls = 0

            if polls <= 3 or polls % 120 == 0:
                logger.info(f"Call state poll {polls}: in_call={in_call} alone={alone}")

            await asyncio.sleep(1)

    def _start_audio_recording(self):
        """Start audio recording using the session's dedicated audio sink."""
        Path(RECORDINGS_DIR).mkdir(parents=True, exist_ok=True)
        filename = f"{self.session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        self.recording_file = str(Path(RECORDINGS_DIR) / filename)
        
        # Store the object key for later upload (remote backends)
        self.storage_path = get_storage().get_file_path(self.session_id, filename)
        
        self.audio_recorder = AudioRecorder(
            output_file=self.recording_file,
            monitor_name=self.monitor_name
        )
        self.audio_recorder.start()
        self.recording_started_at = datetime.now()
        self.status = BotStatus.RECORDING
        logger.info(f"Recording from '{self.monitor_name}' to: {self.recording_file}")

    async def start(self):
        """Start the bot."""
        try:
            logger.info(f"Starting session {self.session_id}")
            self.started_at = datetime.now()
            self.status = BotStatus.JOINING

            await self._setup_browser()
            await self._join_meeting()
            # If not admitted, _join_meeting calls stop() and returns; do not start recording
            if self.status != BotStatus.JOINING:
                return
            self._start_audio_recording()
            self._monitoring_task = asyncio.create_task(self._monitor_presence())
            logger.info("Bot started")

        except Exception as e:
            logger.error(f"Start failed: {e}")
            self.status = BotStatus.ERROR
            self.error_message = str(e)
            self.stopped_at = datetime.now()

            # Send failure webhook notification if configured
            if settings.webhook_url and self.started_at and self.stopped_at:
                try:
                    webhook_payload = WebhookPayload(
                        session_id=self.session_id,
                        meeting_url=self.meeting_url,
                        file_location="",
                        started_at=self.started_at,
                        stopped_at=self.stopped_at
                    )
                    await send_webhook(settings.webhook_url, webhook_payload)
                except Exception as webhook_error:
                    logger.error(f"Error sending failure webhook: {webhook_error}")

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

            # Upload to remote storage (MinIO or Azure Blob)
            storage = get_storage()
            if storage.uses_remote_storage() and self.recording_file and self.storage_path:
                logger.info(f"Uploading recording to storage: {self.storage_path}")
                success = storage.upload_file(self.recording_file, self.storage_path)
                if success:
                    logger.info("Successfully uploaded to storage")
                    try:
                        Path(self.recording_file).unlink(missing_ok=True)
                        logger.info(f"Removed local temporary file: {self.recording_file}")
                    except Exception as e:
                        logger.warning(f"Failed to remove local file: {e}")
                else:
                    logger.error("Failed to upload to storage, keeping local file")

        # Send webhook notification if configured
        if settings.webhook_url and self.recording_file and self.started_at and self.stopped_at:
            try:
                storage = get_storage()
                if storage.uses_remote_storage() and self.storage_path:
                    file_location = storage.get_webhook_file_location(self.storage_path)
                else:
                    file_location = self.recording_file

                webhook_payload = WebhookPayload(
                    session_id=self.session_id,
                    meeting_url=self.meeting_url,
                    file_location=file_location,
                    started_at=self.started_at,
                    stopped_at=self.stopped_at
                )
                await send_webhook(settings.webhook_url, webhook_payload)
            except Exception as e:
                logger.error(f"Error sending webhook: {e}")

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
            except Exception as e:
                logger.warning(f"Error closing page: {e}")

        if self.browser:
            try:
                await self.browser.close()
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")

        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception as e:
                logger.warning(f"Error stopping playwright: {e}")

        # Remove the audio sink
        if self.sink_module_id:
            try:
                subprocess.run(["pactl", "unload-module", self.sink_module_id], check=False)
                logger.info(f"Audio sink removed: {self.sink_name}")
            except Exception as e:
                logger.error(f"Error removing audio sink: {e}")

        if self.status != BotStatus.ERROR:
            self.status = BotStatus.STOPPED
        logger.info(f"Cleanup complete for {self.session_id}")

        # Terminal state reached - let the API retire this session.
        if self.on_stop and not self._on_stop_fired:
            self._on_stop_fired = True
            try:
                self.on_stop(self.session_id)
            except Exception as e:
                logger.error(f"on_stop callback failed: {e}")

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
