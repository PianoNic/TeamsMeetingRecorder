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
    # In the meeting but deliberately not recording (record=false): the bot is
    # there only to play audio in. Distinct from RECORDING so a caller polling
    # /status is never told to wait for a file that will not exist.
    CONNECTED = "connected"
    LEAVING = "leaving"
    # The two ways of not getting in, kept apart from ERROR and from each other:
    # they call for different reactions. DENIED means someone said no, so
    # retrying is pointless without a human. NOT_ADMITTED means nobody answered
    # at all, which is worth retrying later.
    DENIED = "denied"
    NOT_ADMITTED = "not_admitted"
    ERROR = "error"
    STOPPED = "stopped"


class JoinMeetingRequest(BaseModel):
    """Request model for joining a Teams meeting."""
    meeting_url: str = Field(..., description="Microsoft Teams meeting URL")
    display_name: str = Field(..., description="Display name to use in the meeting", max_length=100)
    record: bool = Field(
        True,
        description=(
            "Record the meeting. Set false for a bot that only joins to play "
            "audio in - nothing is captured, saved or uploaded."
        ),
    )

    class Config:
        json_schema_extra = {
            "example": {
                "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
                "display_name": "Recording Bot",
                "record": True
            }
        }


class RecordingSession(BaseModel):
    """Information about a recording session."""
    session_id: str = Field(..., description="Unique session identifier")
    meeting_url: str
    display_name: str
    status: BotStatus
    record: bool = True
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
    record: bool = True
    uptime_seconds: Optional[float] = None
    recording_duration_seconds: Optional[float] = None
    recording_file: Optional[str] = None
    error_message: Optional[str] = None


class PlayFileRequest(BaseModel):
    """Play an audio file that already sits in the media directory."""
    path: str = Field(
        ...,
        description="Path to the audio file, relative to MEDIA_DIR",
    )
    loop: bool = Field(False, description="Repeat until stopped")
    volume: float = Field(1.0, gt=0, le=4.0, description="Playback gain, 1.0 = unchanged")
    unmute: bool = Field(True, description="Unmute the bot first, so the meeting can hear it")

    class Config:
        json_schema_extra = {
            "example": {"path": "hold-music.mp3", "loop": True, "volume": 1.0, "unmute": True}
        }


class OpenStreamRequest(BaseModel):
    """Open an ingest URL another application can push live audio to."""
    format: Optional[str] = Field(
        None,
        description=(
            "ffmpeg input format name. Only needed for headerless audio such as "
            "'s16le'; container formats (mp3, ogg, wav) are detected from the bytes."
        ),
    )
    volume: float = Field(1.0, gt=0, le=4.0, description="Playback gain, 1.0 = unchanged")
    unmute: bool = Field(True, description="Unmute the bot first, so the meeting can hear it")

    class Config:
        json_schema_extra = {"example": {"format": None, "volume": 1.0, "unmute": True}}


class StreamResponse(BaseModel):
    """The ingest endpoint handed back to the application that will push audio."""
    session_id: str
    ingest_url: str = Field(..., description="PUT or POST a live audio stream here")
    token: str = Field(..., description="Secret embedded in ingest_url; treat it as a credential")
    formats: list[str] = Field(
        default_factory=lambda: ["audio/mpeg", "audio/wav", "audio/ogg", "audio/webm"],
        description="Examples of what ffmpeg will decode; anything it supports works",
    )


class AudioStateResponse(BaseModel):
    """What the bot's microphone is doing right now."""
    session_id: str
    status: BotStatus
    record: bool = Field(..., description="Whether this session is recording at all")
    muted: Optional[bool] = Field(None, description="None when the Teams UI cannot be read")
    playing: bool = False
    kind: Optional[str] = Field(None, description="'file' or 'stream' while playing")
    source: Optional[str] = None
    loop: bool = False
    playback_started_at: Optional[datetime] = None
    stream_open: bool = False
    stream_connected: bool = False


class AudioActionResponse(BaseModel):
    """Result of a microphone or playback action."""
    success: bool
    message: str
    state: Optional[AudioStateResponse] = None
