"""FastAPI application for Teams Meeting Recorder."""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from contextlib import asynccontextmanager
from collections import OrderedDict
import hmac
import re
import uuid
import uvicorn
import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional, Set

from app.models import (
    JoinMeetingRequest,
    RecordingResponse,
    StatusResponse,
    RecordingSession,
    BotStatus,
    PlayFileRequest,
    OpenStreamRequest,
    StreamResponse,
    AudioStateResponse,
    AudioActionResponse
)
from app.audio_out import (
    IngestClosed,
    MediaPathRejected,
    PlaybackBusy,
    PlaybackUnavailable,
    media_root,
    resolve_media_path,
)
from app.bot import TeamsBot
from app.config import RECORDINGS_DIR, MEDIA_DIR, API_TITLE, API_VERSION, BROWSER_TIMEOUT, settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global storage for active sessions
active_sessions: Dict[str, TeamsBot] = {}

# Sessions that reached a terminal state. Kept out of /sessions but still
# answerable by /status, so a client polling for the result of its meeting can
# still read the final status and recording path. Bounded so it cannot grow
# without limit.
MAX_FINISHED_SESSIONS = 50
finished_sessions: "OrderedDict[str, TeamsBot]" = OrderedDict()

# Strong references to the running bot tasks. asyncio only keeps weak ones, so
# without this a task can be garbage collected mid-meeting.
_running_tasks: Set[asyncio.Task] = set()


def _retire_session(session_id: str) -> None:
    """Move a finished session out of the active list."""
    bot = active_sessions.pop(session_id, None)
    if bot is None:
        return
    finished_sessions[session_id] = bot
    while len(finished_sessions) > MAX_FINISHED_SESSIONS:
        finished_sessions.popitem(last=False)
    logger.info(f"Session {session_id} retired ({bot.status.value})")


def _lookup_session(session_id: str) -> Optional[TeamsBot]:
    """Find a session whether it is still running or already finished."""
    return active_sessions.get(session_id) or finished_sessions.get(session_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager."""
    logger.info(f"Lobby timeout: {settings.teams_wait_for_lobby} minutes")
    logger.info(f"Browser operation timeout: {BROWSER_TIMEOUT} seconds ({BROWSER_TIMEOUT / 60:.1f} minutes)")
    logger.info("Bot will automatically leave when alone in the meeting")
    Path(RECORDINGS_DIR).mkdir(parents=True, exist_ok=True)
    Path(MEDIA_DIR).mkdir(parents=True, exist_ok=True)
    if settings.mic_playback_enabled:
        logger.info(f"Microphone playback enabled; media directory: {MEDIA_DIR}")
    yield
    logger.info("Shutting down - cleaning up sessions")
    for sid, bot in list(active_sessions.items()):
        try:
            await bot.stop()
        except Exception as e:
            logger.error(f"Cleanup error for {sid}: {e}")


app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description="API for recording Microsoft Teams meetings using a bot",
    lifespan=lifespan
)


# Paths reachable without the access token. "/" is the container health probe.
_OPEN_PATHS = {"/"}

# The ingest endpoint carries its own single-use secret in the URL, because the
# whole point is handing one self-contained URL to another application. It is
# checked against the session's token in constant time by the handler itself.
_INGEST_PATH = re.compile(r"^/audio/[^/]+/ingest/[^/]+$")


def _extract_token(request: Request) -> Optional[str]:
    """Pull the bearer token or X-API-Key from the request headers."""
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[len("bearer "):].strip()
    api_key = request.headers.get("x-api-key")
    if api_key:
        return api_key.strip()
    return None


@app.middleware("http")
async def access_token_guard(request: Request, call_next):
    """Optional inbound auth: when BOT_ACCESS_TOKEN is set, every endpoint
    except the open paths requires it. No-op when the token is unset."""
    expected = settings.bot_access_token
    if (
        expected
        and request.url.path not in _OPEN_PATHS
        and not _INGEST_PATH.match(request.url.path)
    ):
        provided = _extract_token(request)
        if not provided or not hmac.compare_digest(provided, expected):
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": "Unauthorized"},
            )
    return await call_next(request)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": API_TITLE,
        "version": API_VERSION,
        "status": "running",
        "active_sessions": len(active_sessions)
    }


@app.post("/join", response_model=RecordingResponse)
async def join_meeting(request: JoinMeetingRequest):
    """Join a Teams meeting and start recording."""
    bot = TeamsBot(
        meeting_url=request.meeting_url,
        display_name=request.display_name,
        record=request.record,
    )
    bot.on_stop = _retire_session
    active_sessions[bot.session_id] = bot

    task = asyncio.create_task(bot.start())
    _running_tasks.add(task)

    def _on_task_done(finished: asyncio.Task) -> None:
        _running_tasks.discard(finished)
        if finished.cancelled():
            return
        error = finished.exception()
        if error:
            # start() already recorded the failure on the bot; log it here so it
            # does not surface only as "Task exception was never retrieved".
            logger.error(f"Session {bot.session_id} failed to start: {error}")

    task.add_done_callback(_on_task_done)


    return RecordingResponse(
        success=True,
        message=f"Bot joining with session ID: {bot.session_id}",
        session=RecordingSession(
            session_id=bot.session_id,
            meeting_url=request.meeting_url,
            display_name=request.display_name,
            status=BotStatus.JOINING,
            record=bot.record,
            started_at=bot.started_at
        )
    )


@app.post("/stop/{session_id}", response_model=RecordingResponse)
async def stop_recording(session_id: str):
    """Stop an active recording session."""
    bot = active_sessions.get(session_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # stop() -> cleanup() fires on_stop, which retires the session for us.
    await bot.stop()

    return RecordingResponse(
        success=True,
        message=f"Recording stopped for {session_id}",
        session=RecordingSession(
            session_id=bot.session_id,
            meeting_url=bot.meeting_url,
            display_name=bot.display_name,
            status=bot.status,
            record=bot.record,
            started_at=bot.started_at,
            stopped_at=bot.stopped_at,
            recording_file=bot.recording_file
        )
    )


@app.get("/status/{session_id}", response_model=StatusResponse)
async def get_status(session_id: str):
    """Get the status of a recording session."""
    bot = _lookup_session(session_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return StatusResponse(
        session_id=bot.session_id,
        status=bot.status,
        record=bot.record,
        uptime_seconds=bot.get_uptime(),
        recording_duration_seconds=bot.get_recording_duration(),
        recording_file=bot.recording_file,
        error_message=bot.error_message
    )


@app.get("/sessions")
async def list_sessions():
    """List all active recording sessions."""
    return [{
        "session_id": sid,
        "display_name": bot.display_name,
        "status": bot.status.value,
        "record": bot.record,
        "uptime_seconds": bot.get_uptime(),
        "started_at": bot.started_at.isoformat() if bot.started_at else None
    } for sid, bot in active_sessions.items()]


# ---------------------------------------------------------------------------
# Microphone: what the bot says, rather than what it hears.
# ---------------------------------------------------------------------------


def _require_live_session(session_id: str) -> TeamsBot:
    """Fetch a session that is actually in a meeting, or raise."""
    bot = _lookup_session(session_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    if bot.status not in bot.IN_CALL_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"Session {session_id} is not in a meeting (status: {bot.status.value})",
        )
    return bot


def _require_player(session_id: str):
    """Fetch a live session together with its microphone player."""
    bot = _require_live_session(session_id)
    if bot.mic_player is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Microphone playback is disabled for this session "
                "(MIC_PLAYBACK_ENABLED=false)"
            ),
        )
    return bot, bot.mic_player


async def _state(bot: TeamsBot) -> AudioStateResponse:
    return AudioStateResponse(**await bot.get_audio_state())


async def _unmute_for_playback(bot: TeamsBot) -> Optional[str]:
    """Unmute before playing. Returns a note when it could not be done.

    Playing into a muted microphone is silent, but it is not worth failing the
    request over: the audio is already running and the caller can unmute by hand.
    """
    try:
        await bot.set_muted(False)
        return None
    except Exception as e:
        logger.warning(f"Could not unmute for playback: {e}")
        return f"could not unmute automatically ({e})"


@app.get("/audio/{session_id}", response_model=AudioStateResponse)
async def get_audio_state(session_id: str):
    """What the bot's microphone is doing right now."""
    bot = _lookup_session(session_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return await _state(bot)


@app.post("/audio/{session_id}/unmute", response_model=AudioActionResponse)
async def unmute(session_id: str):
    """Unmute the bot so the meeting can hear it."""
    bot = _require_live_session(session_id)
    try:
        await bot.set_muted(False)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return AudioActionResponse(success=True, message="Microphone unmuted", state=await _state(bot))


@app.post("/audio/{session_id}/mute", response_model=AudioActionResponse)
async def mute(session_id: str):
    """Mute the bot again."""
    bot = _require_live_session(session_id)
    try:
        await bot.set_muted(True)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return AudioActionResponse(success=True, message="Microphone muted", state=await _state(bot))


@app.post("/audio/{session_id}/play", response_model=AudioActionResponse)
async def play_file(session_id: str, request: PlayFileRequest):
    """Play a file from the media directory through the bot's microphone."""
    bot, player = _require_player(session_id)

    try:
        path = resolve_media_path(request.path)
    except MediaPathRejected as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        player.play_file(path, loop=request.loop, volume=request.volume)
    except PlaybackBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PlaybackUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    message = f"Playing {path.name}"
    if request.unmute:
        note = await _unmute_for_playback(bot)
        if note:
            message = f"{message}, but {note}"
    return AudioActionResponse(success=True, message=message, state=await _state(bot))


@app.post("/audio/{session_id}/play/upload", response_model=AudioActionResponse)
async def play_upload(
    session_id: str,
    file: UploadFile = File(..., description="Audio file to play into the meeting"),
    loop: bool = Form(False),
    volume: float = Form(1.0),
    unmute: bool = Form(True),
):
    """Upload an audio file and play it straight through the microphone.

    The upload is deleted once playback ends; it is a thing to say, not a thing
    to keep.
    """
    bot, player = _require_player(session_id)

    if not 0 < volume <= 4.0:
        raise HTTPException(status_code=400, detail="volume must be within (0, 4]")

    uploads = media_root() / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    # The client's filename never becomes a path: only its suffix is kept, as a
    # hint for ffmpeg's format detection.
    suffix = Path(file.filename or "").suffix[:16]
    target = uploads / f"{uuid.uuid4().hex}{suffix}"

    limit = settings.max_upload_mb * 1024 * 1024
    written = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds MAX_UPLOAD_MB ({settings.max_upload_mb} MB)",
                    )
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    try:
        player.play_file(target, loop=loop, volume=volume, temp_file=target)
    except PlaybackBusy as e:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail=str(e))
    except PlaybackUnavailable as e:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail=str(e))

    message = f"Playing uploaded {file.filename or target.name}"
    if unmute:
        note = await _unmute_for_playback(bot)
        if note:
            message = f"{message}, but {note}"
    return AudioActionResponse(success=True, message=message, state=await _state(bot))


@app.post("/audio/{session_id}/stream", response_model=StreamResponse)
async def open_stream(session_id: str, request: OpenStreamRequest, http_request: Request):
    """Open an ingest URL for another application to push live audio to.

    The returned URL is self-contained: it carries its own secret, so it can be
    handed to a TTS engine or a player without also handing over the API token.
    """
    bot, player = _require_player(session_id)

    try:
        token = player.open_stream(input_format=request.format, volume=request.volume)
    except PlaybackBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PlaybackUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    base = (settings.public_base_url or str(http_request.base_url)).rstrip("/")
    if request.unmute:
        await _unmute_for_playback(bot)

    return StreamResponse(
        session_id=session_id,
        ingest_url=f"{base}/audio/{session_id}/ingest/{token}",
        token=token,
    )


@app.api_route("/audio/{session_id}/ingest/{token}", methods=["PUT", "POST"])
async def ingest(session_id: str, token: str, request: Request):
    """Receive a live audio stream and play it through the microphone.

    The body is read as it arrives rather than buffered, so this stays live
    audio: what the pushing application sends now is what the meeting hears now.
    The write blocks while the sink is full, which is how backpressure reaches
    an application pushing faster than realtime.
    """
    bot = _lookup_session(session_id)
    player = bot.mic_player if bot else None
    # One 404 for every way of being wrong: an unknown session, a closed stream
    # and a bad token are indistinguishable from outside, so guessing at a token
    # tells the guesser nothing.
    if player is None or not player.token_matches(token):
        raise HTTPException(status_code=404, detail="No such ingest stream")

    received = 0
    try:
        async for chunk in request.stream():
            if not chunk:
                continue
            await player.feed(chunk)
            received += len(chunk)
    except IngestClosed as e:
        logger.info(f"[{session_id}] Ingest ended after {received} bytes: {e}")
        return {"success": False, "bytes_received": received, "message": str(e)}

    logger.info(f"[{session_id}] Ingest complete: {received} bytes")
    return {"success": True, "bytes_received": received, "message": "Stream ended"}


@app.delete("/audio/{session_id}/stream", response_model=AudioActionResponse)
async def close_ingest_stream(session_id: str):
    """Close the ingest stream and invalidate its URL."""
    bot, player = _require_player(session_id)
    was_open = player.close_stream()
    return AudioActionResponse(
        success=True,
        message="Ingest stream closed" if was_open else "No ingest stream was open",
        state=await _state(bot),
    )


@app.post("/audio/{session_id}/stop", response_model=AudioActionResponse)
async def stop_playback(session_id: str, mute_after: bool = False):
    """Stop whatever the bot is playing, optionally muting it again."""
    bot, player = _require_player(session_id)
    was_playing = player.stop()
    player.close_stream()

    message = "Playback stopped" if was_playing else "Nothing was playing"
    if mute_after:
        try:
            await bot.set_muted(True)
            message = f"{message}; microphone muted"
        except Exception as e:
            logger.warning(f"Could not mute after stopping playback: {e}")
            message = f"{message}, but could not mute ({e})"

    return AudioActionResponse(success=True, message=message, state=await _state(bot))


def main():
    """Run the FastAPI application."""
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()
