"""Configuration settings for the Teams Meeting Recorder."""

import os
import re
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings
from typing import Optional


# Hardcoded configuration
DISPLAY_NUMBER = 99
DISPLAY_WIDTH = 1280
DISPLAY_HEIGHT = 720
BROWSER_TIMEOUT = 1440
API_TITLE = "Teams Meeting Recorder API"
DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHANNELS = 2


def _read_app_version() -> str:
    """Read APP_VERSION from application.properties, the file CI bumps on release."""
    properties = Path(__file__).resolve().parent.parent / "application.properties"
    try:
        for line in properties.read_text(encoding="utf-8").splitlines():
            if line.startswith("APP_VERSION="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return "0.0.0"


API_VERSION = _read_app_version()


class Settings(BaseSettings):
    """Application settings."""

    # Waiting room timeout in minutes before bot stops
    teams_wait_for_lobby: int = 30

    # Where recordings are written before upload. Defaults to the container path;
    # override with RECORDINGS_DIR to run outside Docker.
    recordings_dir: str = "/app/recordings"

    # Backstop on how long a single recording may run. Presence detection depends
    # on Teams' UI, so if that ever stops firing the bot would otherwise record
    # until the container restarts. Set to 0 to disable the cap.
    max_recording_minutes: int = 240

    # Microphone playback: give the bot a virtual microphone it can speak
    # through, so audio can be played into the meeting.
    #
    # Off by default, and deliberately so. A real microphone and chromium's
    # --use-fake-device-for-media-stream cannot coexist: the fake device
    # replaces every capture device with a generated beep, so the bot would
    # play into something nobody hears. Dropping that flag is what makes
    # playback possible, but it also takes away the fake camera the Teams
    # prejoin screen has always had. Recording keeps the join path that is
    # known to work; turn this on when you want the bot to talk.
    mic_playback_enabled: bool = False

    # Turn off Teams' noise suppression once in the call. It is designed to
    # strip everything that is not a voice, which is what music and most
    # generated audio look like to it. Only acted on when mic playback is on.
    disable_noise_suppression: bool = True

    # Loop the microphone back into the recording sink, so the saved file
    # contains what the bot played as well as what the meeting said. Off means
    # the recording holds meeting audio only.
    playback_in_recording: bool = True

    # The only directory /audio/{id}/play will read files from. Uploads land
    # here too. Paths outside it are refused: the API can be unauthenticated,
    # and playing arbitrary container files into a meeting is not a feature.
    media_dir: str = "/app/media"

    # Cap on a single upload to /audio/{id}/play/upload, in megabytes.
    max_upload_mb: int = 100

    # Base URL the ingest URL is built from, for deployments behind a proxy
    # where the request's own host header is not reachable by the pushing
    # application. Unset means "use the URL the request came in on".
    public_base_url: Optional[str] = None

    # Storage backend: 'local', 'minio', or 'azure'
    storage_backend: str = "local"

    # MinIO settings (only used when storage_backend='minio')
    minio_endpoint: Optional[str] = None
    minio_access_key: Optional[str] = None
    minio_secret_key: Optional[str] = None
    minio_bucket: str = "recordings"
    minio_secure: bool = True

    # Azure Blob settings (only used when storage_backend='azure')
    azure_storage_connection_string: Optional[str] = None
    # Alternative to the connection string: the account URL
    # (https://<account>.blob.core.windows.net/) authenticated with
    # DefaultAzureCredential, i.e. the managed identity on Azure App Service.
    azure_storage_account_url: Optional[str] = None
    azure_storage_container: str = "meeting-recordings"
    # Optional public base for webhook file_location URLs (e.g. Azurite http://127.0.0.1:41000/devstoreaccount1)
    azure_storage_public_endpoint: Optional[str] = None

    # Webhook settings (optional)
    # Called when a recording finishes saving (both local and MinIO)
    webhook_url: Optional[str] = None

    # Optional shared secret sent as the X-Webhook-Secret header on webhook POSTs
    # for the receiver to verify. Set via env WEBHOOK_SECRET. Leave unset to send
    # no signature.
    webhook_secret: Optional[str] = None

    # Optional shared secret protecting all endpoints except "/" (the health
    # probe). Set via env BOT_ACCESS_TOKEN. When set, every request must send
    # `Authorization: Bearer <token>` or `X-API-Key: <token>` (401 otherwise).
    # Leave unset to keep the recorder open (no inbound auth).
    bot_access_token: Optional[str] = None

    @field_validator("*", mode="before")
    @classmethod
    def _expand_env_refs(cls, value):
        """Resolve `${OTHER_VAR}` in any value to that variable's current value.

        Lets a deployment point e.g. AZURE_STORAGE_CONTAINER at a platform-managed
        variable (`${Storage__BlobContainerName}`) instead of copying the value.
        An unset reference is left as written so the mistake is visible.
        """
        if isinstance(value, str) and "${" in value:
            # ponytail: one level of indirection - no recursion, no defaults syntax
            value = re.sub(r"\$\{([^}]+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), value)
        return value

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

# Kept as module constants so call sites read the same way as the other config
# values; the values themselves are env-overridable via Settings.
RECORDINGS_DIR = settings.recordings_dir
MEDIA_DIR = settings.media_dir
