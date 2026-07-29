"""FastAPI application for Teams Meeting Recorder."""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, JSONResponse
from contextlib import asynccontextmanager
from collections import OrderedDict
import hmac
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
    BotStatus
)
from app.bot import TeamsBot
from app.config import RECORDINGS_DIR, API_TITLE, API_VERSION, BROWSER_TIMEOUT, settings

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
    if expected and request.url.path not in _OPEN_PATHS:
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
    bot = TeamsBot(meeting_url=request.meeting_url, display_name=request.display_name)
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
        "uptime_seconds": bot.get_uptime(),
        "started_at": bot.started_at.isoformat() if bot.started_at else None
    } for sid, bot in active_sessions.items()]


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
