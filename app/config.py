"""Configuration settings for the Teams Meeting Recorder."""

from pydantic_settings import BaseSettings
from typing import Optional


# Hardcoded configuration
DISPLAY_NUMBER = 99
DISPLAY_WIDTH = 1280
DISPLAY_HEIGHT = 720
BROWSER_TIMEOUT = 1440
RECORDINGS_DIR = "/app/recordings"
LOGS_DIR = "/app/logs"
API_TITLE = "Teams Meeting Recorder API"
API_VERSION = "1.0.0"
DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHANNELS = 2
PULSEAUDIO_MONITOR_NAME = "teams_virtual_sink.monitor"
PULSEAUDIO_SINK_NAME = "teams_virtual_sink"


class Settings(BaseSettings):
    """Application settings."""

    # Waiting room timeout in minutes before bot stops
    teams_wait_for_lobby: int = 30

    # Debug screenshots
    debug_screenshots: bool = False

    # Storage backend: 'local' or 'minio'
    storage_backend: str = "local"

    # MinIO settings (only used when storage_backend='minio')
    minio_endpoint: Optional[str] = None
    minio_access_key: Optional[str] = None
    minio_secret_key: Optional[str] = None
    minio_bucket: str = "recordings"
    minio_secure: bool = True

    # Webhook settings (optional)
    # Called when a recording finishes saving (both local and MinIO)
    webhook_url: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
