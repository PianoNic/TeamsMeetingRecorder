"""Configuration settings for the Teams Meeting Recorder."""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings."""

    # API Settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_title: str = "Teams Meeting Recorder API"
    api_version: str = "1.0.0"

    # Recording Settings
    recordings_dir: str = "/app/recordings"
    logs_dir: str = "/app/logs"
    default_sample_rate: int = 48000
    default_channels: int = 2
    audio_format: str = "WAV"

    # Browser Settings
    display_width: int = 1920
    display_height: int = 1080
    display_number: int = 99
    browser_headless: bool = False  # Set to False for VNC viewing
    vnc_port: int = 5900

    # Selenium Settings
    selenium_timeout: int = 30
    implicit_wait: int = 10
    page_load_timeout: int = 60

    # Teams Settings
    teams_join_timeout: int = 60
    teams_wait_for_lobby: int = 30

    # PulseAudio Settings
    pulseaudio_sink_name: str = "teams_virtual_sink"
    pulseaudio_monitor_name: str = "teams_virtual_sink.monitor"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
