"""Data models for the Teams Meeting Recorder API."""

from pydantic import BaseModel, HttpUrl, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class BotStatus(str, Enum):
    """Status of the recording bot."""
    IDLE = "idle"
    JOINING = "joining"
    RECORDING = "recording"
    LEAVING = "leaving"
    ERROR = "error"
    STOPPED = "stopped"


class JoinMeetingRequest(BaseModel):
    """Request model for joining a Teams meeting."""
    meeting_url: str = Field(..., description="Microsoft Teams meeting URL")
    display_name: str = Field(..., description="Display name to use in the meeting", max_length=100)

    class Config:
        json_schema_extra = {
            "example": {
                "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
                "display_name": "Recording Bot"
            }
        }


class RecordingSession(BaseModel):
    """Information about a recording session."""
    session_id: str = Field(..., description="Unique session identifier")
    meeting_url: str
    display_name: str
    status: BotStatus
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    recording_file: Optional[str] = None
    error_message: Optional[str] = None


class RecordingResponse(BaseModel):
    """Response for recording operations."""
    success: bool
    message: str
    session: Optional[RecordingSession] = None


class StatusResponse(BaseModel):
    """Response for status checks."""
    session_id: str
    status: BotStatus
    uptime_seconds: Optional[float] = None
    recording_duration_seconds: Optional[float] = None
    recording_file: Optional[str] = None
    error_message: Optional[str] = None
