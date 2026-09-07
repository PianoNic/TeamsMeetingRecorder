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
from app.audio_out import MicrophonePlayer
from app.models import BotStatus
from app.recorder import AudioRecorder
from app.storage import get_storage
from app.webhook import send_webhook, WebhookPayload

logger = logging.getLogger(__name__)


class MeetingDenied(RuntimeError):
    """An organiser declined the bot from the lobby."""


class NotAdmitted(RuntimeError):
    """Nobody accepted or declined the bot before the lobby timeout."""


class TeamsBot:
    """Bot that joins Teams meetings and records audio using Playwright."""

    def __init__(
        self,
        meeting_url: str,
        display_name: str,
        record: bool = True
    ):
        """
        Initialize the Teams bot.

        Args:
            meeting_url: Microsoft Teams meeting URL
            display_name: Display name to use in the meeting
            record: Whether to record the meeting. False joins the meeting
                without capturing anything, for a bot that is only there to
                speak.
        """
        self.session_id = str(uuid.uuid4())
        self.meeting_url = meeting_url
        self.display_name = display_name
        self.record = record

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

        # Outbound audio: a second sink whose monitor is the browser's
        # microphone. Only created when mic playback is enabled.
        self.mic_sink_name: Optional[str] = None
        self.mic_source_name: Optional[str] = None
        self.mic_module_id: Optional[str] = None
        self.mic_source_module_id: Optional[str] = None
        self.loopback_module_id: Optional[str] = None
        self.mic_player: Optional[MicrophonePlayer] = None

        # Invoked once with this session's id when the bot reaches a terminal
        # state, so the API can retire it from the active session list.
        self.on_stop: Optional[Callable[[str], None]] = None
        self._on_stop_fired = False

        logger.info(f"Initialized bot with session ID: {self.session_id}")

    def _create_null_sink(self, sink_name: str, description: str) -> str:
        """Create one virtual audio sink and return its module id."""
        try:
            logger.info(f"Creating audio sink '{sink_name}' for session {self.session_id}")

            cmd = [
                "pactl", "load-module", "module-null-sink",
                f"sink_name={sink_name}",
                f"sink_properties=device.description='{description}'"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            module_id = result.stdout.strip()

            # Do NOT set as default sink - let --alsa-output-device handle routing
            # Setting as default would route ALL system audio to this sink

            logger.info(f"Audio sink created: {sink_name} (module {module_id})")
            return module_id

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create audio sink: {e.stderr}")
            raise Exception(f"Failed to create audio sink: {e.stderr}")

    def _create_audio_sink(self) -> tuple[str, str, str]:
        """Create the sink that carries meeting audio into the recorder."""
        sink_name = f"teams_sink_{self.session_id[:8]}"
        monitor_name = f"{sink_name}.monitor"
        module_id = self._create_null_sink(
            sink_name, f"Teams_Session_{self.session_id[:8]}"
        )
        return sink_name, monitor_name, module_id

    def _create_mic_sink(self) -> str:
        """Create the microphone the browser captures from, and return its name.

        Two modules, both needed. A null sink is what audio gets played into,
        and module-remap-source turns that sink's monitor into a real source:
        chromium does not enumerate monitor sources at all, so handing it
        `<sink>.monitor` leaves getUserMedia with no audio device whatsoever.

        Kept separate from the recording sink on purpose. Pointing the browser's
        microphone at the sink it also writes to would feed the meeting back
        into itself the moment the bot unmutes.
        """
        sink_name = f"teams_mic_{self.session_id[:8]}"
        source_name = f"teams_mic_src_{self.session_id[:8]}"

        self.mic_module_id = self._create_null_sink(
            sink_name, f"Teams_Mic_{self.session_id[:8]}"
        )
        self.mic_sink_name = sink_name

        try:
            result = subprocess.run(
                [
                    "pactl", "load-module", "module-remap-source",
                    f"source_name={source_name}",
                    f"master={sink_name}.monitor",
                    f"source_properties=device.description='Teams_Microphone_{self.session_id[:8]}'",
                ],
                capture_output=True, text=True, check=True,
            )
            self.mic_source_module_id = result.stdout.strip()
            self.mic_source_name = source_name
            logger.info(
                f"Microphone source created: {source_name} <- {sink_name}.monitor "
                f"(module {self.mic_source_module_id})"
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create microphone source: {e.stderr}")
            raise Exception(f"Failed to create microphone source: {e.stderr}")

        self.mic_player = MicrophonePlayer(self.session_id, sink_name)

        if settings.playback_in_recording and self.record:
            # So the saved file contains what the bot played, not just what it
            # heard. One-directional: mic monitor -> recording sink, never back.
            # Pointless when there is no recording to put it in.
            try:
                result = subprocess.run(
                    [
                        "pactl", "load-module", "module-loopback",
                        f"source={sink_name}.monitor",
                        f"sink={self.sink_name}",
                        "latency_msec=50",
                    ],
                    capture_output=True, text=True, check=True,
                )
                self.loopback_module_id = result.stdout.strip()
                logger.info(
                    f"Mic loopback into recording: {sink_name}.monitor -> {self.sink_name} "
                    f"(module {self.loopback_module_id})"
                )
            except subprocess.CalledProcessError as e:
                # Playback still works without it; only the recording loses the
                # bot's own audio. Not worth failing the meeting over.
                logger.warning(f"Could not loop playback into the recording: {e.stderr}")

        return source_name

    def _build_launch_options(self, mic_source: str) -> tuple[dict, list[str]]:
        """The env and argv chromium is launched with.

        Split out from _setup_browser so the audio wiring can be checked without
        starting a browser: which source the microphone reads from, and whether
        the fake capture device is in play, decide whether the bot can be heard
        at all.
        """
        # Pin the sink on the launched process only. Mutating os.environ here would
        # race: with two sessions starting at once the second overwrites the value
        # before the first chromium has forked, and both meetings land in one sink.
        browser_env = {
            **os.environ,
            "DISPLAY": f":{DISPLAY_NUMBER}",
            "PULSE_SINK": self.sink_name,
            "PULSE_SOURCE": mic_source,
        }

        browser_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            f"--window-size={DISPLAY_WIDTH},{DISPLAY_HEIGHT}",
            "--autoplay-policy=no-user-gesture-required",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=AudioServiceOutOfProcess",
        ]
        if not settings.mic_playback_enabled:
            # The fake device replaces every real capture device with a generated
            # beep, so it cannot coexist with playing real audio through the
            # microphone. With playback off, the flags are what they always were.
            browser_args.insert(3, "--use-fake-device-for-media-stream")

        return browser_env, browser_args

    async def _setup_browser(self):
        """Setup browser with dedicated audio sink."""
        logger.info(f"Setting up browser for session {self.session_id}")

        # Create dedicated audio sink FIRST
        self.sink_name, self.monitor_name, self.sink_module_id = self._create_audio_sink()

        # What the browser will hear as its microphone. Without mic playback
        # this stays the recording monitor, exactly as before.
        if settings.mic_playback_enabled:
            mic_source = self._create_mic_sink()
        else:
            mic_source = self.monitor_name

        browser_env, browser_args = self._build_launch_options(mic_source)

        logger.info(f"Browser will use PULSE_SINK={self.sink_name} PULSE_SOURCE={mic_source}")

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=False,
            env=browser_env,
            args=browser_args
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

        await self._dismiss_no_devices_prompt(self.NO_DEVICES_FIRST_WAIT_MS)

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
            # It can also arrive late, after the name is filled in, and it would
            # swallow the click below just as silently.
            await self._dismiss_no_devices_prompt(self.NO_DEVICES_RECHECK_MS)
            await self.page.locator("button[data-tid='prejoin-join-button']").first.click()
            logger.info("Request Joining meeting...")
        except Exception as e:
            logger.error(f"Problem clicking on join: {e}")

        # Wait for the lobby to resolve one way or the other. Three outcomes:
        # admitted (hangup button appears), denied (Teams says so outright), or
        # nobody acted at all (timeout). All three have to be told apart - being
        # turned away is a different answer than being ignored, and both are
        # failures the caller needs to hear about.
        hangup = self.page.locator("button[id='hangup-button']")
        denied = self.page.get_by_text(self.DENIED_TEXT, exact=False)
        timeout_ms = settings.teams_wait_for_lobby * 60 * 1000

        try:
            await hangup.or_(denied).first.wait_for(state="visible", timeout=timeout_ms)
        except Exception:
            raise NotAdmitted(
                f"Never admitted: nobody accepted or declined the bot within "
                f"{settings.teams_wait_for_lobby} minutes"
            )

        try:
            was_denied = await denied.first.is_visible(timeout=2000)
        except Exception:
            was_denied = False

        if was_denied:
            raise MeetingDenied("Denied entry to the meeting")

        logger.info("Joined meeting")

        # Only reachable once in the call - the switch lives in the in-call
        # toolbar, not on the prejoin screen.
        await self._disable_noise_suppression()

    # Teams throws up an interstitial over the prejoin screen when a device it
    # asked for is missing, and nothing behind it can be clicked until it goes.
    # The bot has no camera once the fake device is gone, so this can appear on
    # the playback path - never on the default one, which still has a fake
    # camera and never sees this dialog.
    NO_DEVICES_BUTTON = "button:has-text('Continue without audio or video')"

    # The overlay is rendered well after DOMContentLoaded - measured at between
    # five and ten seconds against a live meeting - so the first wait has to be
    # generous. Everything behind it is unclickable until it goes, and Playwright
    # reports that as an actionability retry, not an error: the join click simply
    # blocks until the page timeout (24 minutes) with nothing in the log.
    NO_DEVICES_FIRST_WAIT_MS = 20000

    # A second, cheap look right before the join click, in case it arrived late.
    NO_DEVICES_RECHECK_MS = 3000

    async def _dismiss_no_devices_prompt(self, timeout_ms: int):
        """Clear the "are you sure you don't want audio or video?" overlay.

        Teams shows it when a device it asked for is missing. With microphone
        playback on there is no camera, because the fake capture device that
        used to supply one cannot coexist with a real microphone. The prompt is
        about the camera only - the mic is listed and selected either way.

        Only runs with playback on, so the join path that is known to work is
        left exactly as it was.
        """
        if not settings.mic_playback_enabled:
            return
        try:
            button = self.page.locator(self.NO_DEVICES_BUTTON).first
            await button.wait_for(state="visible", timeout=timeout_ms)
        except Exception:
            return  # No overlay, nothing to do.

        try:
            await button.click(timeout=self.MONITOR_QUERY_TIMEOUT_MS)
            logger.info("Dismissed the 'no audio or video' prompt (no camera in the container)")
        except Exception as e:
            logger.warning(f"Could not dismiss the 'no audio or video' prompt: {e}")

    # Path through the in-call UI to the noise-suppression switch:
    # the chevron beside the Mic button, then "More audio settings".
    AUDIO_CONFIGURE_BUTTON = "button#audio-button-configure"
    MORE_AUDIO_SETTINGS_BUTTON = "button[data-tid='more-audio-settings-button']"
    NOISE_SUPPRESSION_SWITCH = "input[data-tid='background-suppression-switch']"

    async def _disable_noise_suppression(self):
        """Turn off Teams' noise suppression so music survives the trip.

        Suppression is built to remove everything that is not a voice, which is
        exactly what music and most generated audio look like to it: the bot is
        audible either way, but quietly mangled. On by default in Teams, so it
        has to be turned off explicitly once the bot is in the call.

        Best-effort. A UI change here costs audio quality, not the meeting, so
        every failure is logged and swallowed rather than dropping the session.
        """
        if not (settings.mic_playback_enabled and settings.disable_noise_suppression):
            return

        try:
            await self.page.locator(self.AUDIO_CONFIGURE_BUTTON).first.click(
                timeout=self.MONITOR_QUERY_TIMEOUT_MS
            )
            await self.page.locator(self.MORE_AUDIO_SETTINGS_BUTTON).first.click(
                timeout=self.MONITOR_QUERY_TIMEOUT_MS
            )

            switch = self.page.locator(self.NOISE_SUPPRESSION_SWITCH).first
            await switch.wait_for(state="attached", timeout=self.MONITOR_QUERY_TIMEOUT_MS)

            if await switch.is_checked():
                await switch.click(timeout=self.MONITOR_QUERY_TIMEOUT_MS)
                # Confirm, rather than assume the click landed on the styled
                # element that sits over the real checkbox.
                if await switch.is_checked():
                    logger.warning("Noise suppression switch did not turn off")
                else:
                    logger.info("Noise suppression turned off")
            else:
                logger.info("Noise suppression was already off")
        except Exception as e:
            logger.warning(f"Could not turn off noise suppression: {e}")
        finally:
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass

    async def _leave_meeting(self):
        """Leave the meeting."""
        leave_btn = self.page.locator("button[id='hangup-button']").first
        if await leave_btn.is_visible(timeout=5000):
            await leave_btn.click()
            logger.info("Left meeting")
            await self.page.wait_for_timeout(2000)

    # The in-call microphone toggle. The current web client calls it
    # #mic-button and gives it no data-tid at all; the other two are kept as
    # fallbacks for clients that name it differently. Confirmed against a live
    # meeting: aria-label is "Unmute mic" while muted and "Mute mic" while live.
    MIC_BUTTON = (
        "button#mic-button, button#microphone-button, button[data-tid='toggle-mute']"
    )

    # How many times to re-read the button after clicking before giving up on
    # the toggle having landed. Teams re-renders the toolbar on state change,
    # so the first read after a click can still show the old label.
    MUTE_VERIFY_ATTEMPTS = 5

    async def _read_muted(self) -> Optional[bool]:
        """Is the bot's microphone muted? None when it cannot be determined.

        Read from the accessible label rather than a class name: "Unmute" is
        what the button offers to do, so seeing it means the mic is off. The
        substring order matters - "unmute" contains "mute".
        """
        try:
            button = self.page.locator(self.MIC_BUTTON).first
            label = (await button.get_attribute(
                "aria-label", timeout=self.MONITOR_QUERY_TIMEOUT_MS
            )) or ""
            label = label.lower()
            if "unmute" in label:
                return True
            if "mute" in label:
                return False

            # Older toolbars expose the state as aria-pressed on a toggle
            # button, where pressed means the mic is live.
            pressed = await button.get_attribute(
                "aria-pressed", timeout=self.MONITOR_QUERY_TIMEOUT_MS
            )
            if pressed in ("true", "false"):
                return pressed == "false"
        except Exception as e:
            logger.warning(f"Could not read microphone state: {e}")
        return None

    async def set_muted(self, muted: bool) -> bool:
        """Mute or unmute the bot in the meeting. Returns the resulting state.

        Idempotent: clicking a toggle blind would turn the microphone on when
        asked to turn it off, so the current state is read first and the click
        only happens when it would actually change something.
        """
        if self.status not in self.IN_CALL_STATES:
            raise RuntimeError(f"Not in a meeting (status: {self.status.value})")

        current = await self._read_muted()
        if current == muted:
            logger.info(f"Microphone already {'muted' if muted else 'unmuted'}")
            return muted

        button = self.page.locator(self.MIC_BUTTON).first
        await button.click(timeout=self.MONITOR_QUERY_TIMEOUT_MS)

        # Confirm rather than assume. A click that silently did nothing would
        # otherwise be reported as a successful unmute and the bot would play
        # audio nobody hears.
        for _ in range(self.MUTE_VERIFY_ATTEMPTS):
            await asyncio.sleep(0.3)
            state = await self._read_muted()
            if state == muted:
                logger.info(f"Microphone {'muted' if muted else 'unmuted'}")
                return muted

        if state is None:
            # The click went through; we just cannot read the result back.
            logger.warning("Microphone toggled but the resulting state is unreadable")
            return muted

        raise RuntimeError(
            f"Microphone did not {'mute' if muted else 'unmute'}; still "
            f"{'muted' if state else 'unmuted'}"
        )

    async def get_audio_state(self) -> dict:
        """Microphone and playback state, for GET /audio/{session_id}."""
        state = {
            "session_id": self.session_id,
            "status": self.status,
            "record": self.record,
            "muted": None,
            "playing": False,
            "kind": None,
            "source": None,
            "loop": False,
            "playback_started_at": None,
            "stream_open": False,
            "stream_connected": False,
        }
        if self.status in self.IN_CALL_STATES and self.page:
            state["muted"] = await self._read_muted()
        if self.mic_player:
            state.update(self.mic_player.status())
        return state

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
    # States that mean the session failed. cleanup() must not stamp STOPPED
    # over any of them.
    TERMINAL_FAILURES = (BotStatus.DENIED, BotStatus.NOT_ADMITTED, BotStatus.ERROR)

    ALONE_TEXT = "Waiting for others to join"

    # The bot is in the call in both of these. A speak-only session never
    # reaches RECORDING, so anything gated on "still in the meeting" has to
    # accept CONNECTED too or it would tear down the moment it joined.
    IN_CALL_STATES = (BotStatus.RECORDING, BotStatus.CONNECTED)

    # Shown on the bot's own page when an organiser declines it from the lobby.
    # Same en-US assumption as ALONE_TEXT.
    DENIED_TEXT = "denied access to the meeting"

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

        while self.status in self.IN_CALL_STATES:
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
        if not self.record:
            # Speak-only session. The sink and the browser are wired up exactly
            # the same way; nothing is reading the monitor, so nothing is kept.
            # The clock still starts, so max_recording_minutes caps how long a
            # speak-only bot can sit in a meeting just as it caps a recording.
            self.recording_started_at = datetime.now()
            self.status = BotStatus.CONNECTED
            logger.info("Joined without recording (record=false)")
            return

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
            self._start_audio_recording()
            self._monitoring_task = asyncio.create_task(self._monitor_presence())
            logger.info("Bot started")

        except Exception as e:
            logger.error(f"Start failed: {e}")
            # Not getting in is a distinct outcome, not a malfunction, and being
            # refused is not the same as being ignored.
            if isinstance(e, MeetingDenied):
                self.status = BotStatus.DENIED
            elif isinstance(e, NotAdmitted):
                self.status = BotStatus.NOT_ADMITTED
            else:
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

        # Silence the microphone before hanging up, so a half-played track
        # cannot keep feeding the sink while the page is torn down.
        if self.mic_player:
            self.mic_player.close()

        if self.page and self.status in self.IN_CALL_STATES:
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

        # Send webhook notification if configured. A speak-only session has no
        # file to point at but still finished, so it reports an empty location
        # rather than going silent - same shape the failure webhook already uses.
        finished = self.recording_file or not self.record
        if settings.webhook_url and finished and self.started_at and self.stopped_at:
            try:
                storage = get_storage()
                if not self.recording_file:
                    file_location = ""
                elif storage.uses_remote_storage() and self.storage_path:
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

        if self.mic_player:
            try:
                self.mic_player.close()
            except Exception as e:
                logger.warning(f"Error stopping microphone playback: {e}")

        # Unload in reverse order of creation: the loopback holds references to
        # both sinks, so tearing a sink out from under it leaves a dead module.
        for module_id, label in (
            (self.loopback_module_id, "mic loopback"),
            (self.mic_source_module_id, f"mic source {self.mic_source_name}"),
            (self.mic_module_id, f"mic sink {self.mic_sink_name}"),
            (self.sink_module_id, f"audio sink {self.sink_name}"),
        ):
            if not module_id:
                continue
            try:
                subprocess.run(["pactl", "unload-module", module_id], check=False)
                logger.info(f"Removed {label}")
            except Exception as e:
                logger.error(f"Error removing {label}: {e}")

        if self.status not in self.TERMINAL_FAILURES:
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
