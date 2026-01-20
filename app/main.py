"""FastAPI application for Teams Meeting Recorder."""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import uvicorn
import asyncio
import logging
from pathlib import Path
from typing import Dict

from app.config import settings
from app.models import (
    JoinMeetingRequest,
    RecordingResponse,
    StatusResponse,
    RecordingSession,
    BotStatus
)
from app.bot import TeamsBot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"{settings.logs_dir}/app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global storage for active sessions
active_sessions: Dict[str, TeamsBot] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager."""
    logger.info("Starting Teams Meeting Recorder API")
    Path(settings.recordings_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.logs_dir).mkdir(parents=True, exist_ok=True)
    yield
    logger.info("Shutting down - cleaning up sessions")
    for sid, bot in list(active_sessions.items()):
        try:
            await bot.stop()
        except Exception as e:
            logger.error(f"Cleanup error for {sid}: {e}")


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description="API for recording Microsoft Teams meetings using a bot",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.api_title,
        "version": settings.api_version,
        "status": "running",
        "active_sessions": len(active_sessions)
    }


@app.post("/join", response_model=RecordingResponse)
async def join_meeting(request: JoinMeetingRequest):
    """Join a Teams meeting and start recording."""
    bot = TeamsBot(meeting_url=request.meeting_url, display_name=request.display_name)
    active_sessions[bot.session_id] = bot
    asyncio.create_task(bot.start())
    
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
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    bot = active_sessions.pop(session_id)
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
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    bot = active_sessions[session_id]
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
    return {
        "active_sessions": len(active_sessions),
        "sessions": [{
            "session_id": sid,
            "display_name": bot.display_name,
            "status": bot.status.value,
            "uptime_seconds": bot.get_uptime()
        } for sid, bot in active_sessions.items()]
    }


@app.get("/download/{session_id}")
async def download_recording(session_id: str):
    """Download a completed recording."""
    # Check active sessions first
    if session_id in active_sessions:
        recording_file = active_sessions[session_id].recording_file
        if recording_file and Path(recording_file).exists():
            return FileResponse(recording_file, media_type="audio/wav", filename=Path(recording_file).name)
    
    # Search recordings directory
    for file in Path(settings.recordings_dir).glob(f"{session_id}*.wav"):
        return FileResponse(str(file), media_type="audio/wav", filename=file.name)
    
    raise HTTPException(status_code=404, detail=f"Recording for {session_id} not found")


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Force delete a session and clean up resources."""
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    await active_sessions.pop(session_id).stop()
    return {"message": f"Session {session_id} deleted"}


def main():
    """Run the FastAPI application."""
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()
