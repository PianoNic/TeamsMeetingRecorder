"""FastAPI application for Teams Meeting Recorder."""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import uvicorn
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
    """Lifecycle manager for the FastAPI app."""
    # Startup
    logger.info("Starting Teams Meeting Recorder API")
    Path(settings.recordings_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.logs_dir).mkdir(parents=True, exist_ok=True)
    yield
    # Shutdown
    logger.info("Shutting down Teams Meeting Recorder API")
    for session_id, bot in active_sessions.items():
        logger.info(f"Cleaning up session {session_id}")
        try:
            bot.stop()
        except Exception as e:
            logger.error(f"Error cleaning up session {session_id}: {e}")


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
async def join_meeting(
    request: JoinMeetingRequest,
    background_tasks: BackgroundTasks
):
    """
    Join a Teams meeting and start recording.

    Args:
        request: Meeting details including URL and display name

    Returns:
        RecordingResponse with session information
    """
    try:
        logger.info(f"Received join request for meeting with name: {request.display_name}")

        # Create new bot instance
        bot = TeamsBot(
            meeting_url=request.meeting_url,
            display_name=request.display_name,
            record_audio=request.record_audio,
            max_duration_minutes=request.max_duration_minutes
        )

        # Store in active sessions
        active_sessions[bot.session_id] = bot

        # Start bot in background
        background_tasks.add_task(bot.start)

        session = RecordingSession(
            session_id=bot.session_id,
            meeting_url=request.meeting_url,
            display_name=request.display_name,
            status=BotStatus.JOINING,
            started_at=bot.started_at
        )

        return RecordingResponse(
            success=True,
            message=f"Bot is joining the meeting with session ID: {bot.session_id}",
            session=session
        )

    except Exception as e:
        logger.error(f"Error joining meeting: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/stop/{session_id}", response_model=RecordingResponse)
async def stop_recording(session_id: str):
    """
    Stop an active recording session.

    Args:
        session_id: The session ID to stop

    Returns:
        RecordingResponse with final session information
    """
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    try:
        bot = active_sessions[session_id]
        logger.info(f"Stopping session {session_id}")

        bot.stop()

        session = RecordingSession(
            session_id=bot.session_id,
            meeting_url=bot.meeting_url,
            display_name=bot.display_name,
            status=bot.status,
            started_at=bot.started_at,
            stopped_at=bot.stopped_at,
            recording_file=bot.recording_file
        )

        # Remove from active sessions
        del active_sessions[session_id]

        return RecordingResponse(
            success=True,
            message=f"Recording stopped for session {session_id}",
            session=session
        )

    except Exception as e:
        logger.error(f"Error stopping session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status/{session_id}", response_model=StatusResponse)
async def get_status(session_id: str):
    """
    Get the status of a recording session.

    Args:
        session_id: The session ID to check

    Returns:
        StatusResponse with current session status
    """
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
    """
    List all active recording sessions.

    Returns:
        List of active session IDs and their status
    """
    sessions = []
    for session_id, bot in active_sessions.items():
        sessions.append({
            "session_id": session_id,
            "display_name": bot.display_name,
            "status": bot.status.value,
            "uptime_seconds": bot.get_uptime()
        })

    return {
        "active_sessions": len(sessions),
        "sessions": sessions
    }


@app.get("/download/{session_id}")
async def download_recording(session_id: str):
    """
    Download a completed recording.

    Args:
        session_id: The session ID of the recording

    Returns:
        The audio file
    """
    # Check both active and completed sessions
    recording_file = None

    if session_id in active_sessions:
        bot = active_sessions[session_id]
        if bot.recording_file and Path(bot.recording_file).exists():
            recording_file = bot.recording_file
    else:
        # Search in recordings directory
        recordings_path = Path(settings.recordings_dir)
        for file in recordings_path.glob(f"{session_id}*.wav"):
            recording_file = str(file)
            break

    if not recording_file:
        raise HTTPException(status_code=404, detail=f"Recording for session {session_id} not found")

    return FileResponse(
        path=recording_file,
        media_type="audio/wav",
        filename=Path(recording_file).name
    )


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """
    Force delete a session and clean up resources.

    Args:
        session_id: The session ID to delete

    Returns:
        Confirmation message
    """
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    try:
        bot = active_sessions[session_id]
        bot.stop()
        del active_sessions[session_id]

        return {"message": f"Session {session_id} deleted successfully"}

    except Exception as e:
        logger.error(f"Error deleting session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
