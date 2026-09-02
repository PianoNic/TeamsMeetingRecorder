"""Storage backend abstraction for recordings."""

import logging
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from minio import Minio
from minio.error import S3Error

from app.config import settings, RECORDINGS_DIR

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    def get_file_path(self, session_id: str, filename: str) -> str:
        """Get the path/key where a file should be stored."""
        pass

    @abstractmethod
    def upload_file(self, local_path: str, storage_path: str) -> bool:
        """Upload a file to storage. Returns True on success."""
        pass

    @abstractmethod
    def get_webhook_file_location(self, storage_path: str) -> str:
        """Return file_location for webhook consumers (URL or blob path)."""
        pass

    def uses_remote_storage(self) -> bool:
        """Whether recordings are uploaded to remote object storage."""
        return False


class LocalStorage(StorageBackend):
    """Local filesystem storage backend."""

    def __init__(self):
        """Initialize local storage."""
        self.base_dir = Path(RECORDINGS_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Local storage initialized: {self.base_dir}")

    def get_file_path(self, session_id: str, filename: str) -> str:
        """Get the local file path."""
        return str(self.base_dir / filename)

    def upload_file(self, local_path: str, storage_path: str) -> bool:
        """For local storage, the file is already in place."""
        return Path(local_path).exists()

    def get_webhook_file_location(self, storage_path: str) -> str:
        return storage_path


class MinIOStorage(StorageBackend):
    """MinIO/S3-compatible storage backend."""

    def __init__(self):
        """Initialize MinIO client."""
        if not settings.minio_endpoint or not settings.minio_access_key or not settings.minio_secret_key:
            raise ValueError(
                "MinIO credentials not configured. Check MINIO_ENDPOINT, MINIO_ACCESS_KEY, and MINIO_SECRET_KEY"
            )

        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self.bucket = settings.minio_bucket

        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"Created MinIO bucket: {self.bucket}")
            else:
                logger.info(f"Using existing MinIO bucket: {self.bucket}")
        except S3Error as e:
            logger.error(f"Failed to initialize MinIO bucket: {e}")
            raise

    def uses_remote_storage(self) -> bool:
        return True

    def get_file_path(self, session_id: str, filename: str) -> str:
        """Get the MinIO object key (path in bucket)."""
        return f"{session_id}/{filename}"

    def upload_file(self, local_path: str, storage_path: str) -> bool:
        """Upload a file to MinIO."""
        try:
            self.client.fput_object(
                bucket_name=self.bucket,
                object_name=storage_path,
                file_path=local_path,
                content_type="audio/wav",
            )
            logger.info(f"Uploaded to MinIO: {storage_path}")
            return True
        except S3Error as e:
            logger.error(f"Failed to upload to MinIO {storage_path}: {e}")
            return False

    def get_webhook_file_location(self, storage_path: str) -> str:
        protocol = "https" if settings.minio_secure else "http"
        return f"{protocol}://{settings.minio_endpoint}/{self.bucket}/{storage_path}"


class AzureBlobStorage(StorageBackend):
    """Azure Blob Storage backend (production or Azurite emulator)."""

    def __init__(self):
        from azure.core.exceptions import ResourceExistsError
        from azure.storage.blob import ContentSettings, PublicAccess

        self.container = settings.azure_storage_container
        self._public_endpoint = (settings.azure_storage_public_endpoint or "").rstrip("/")
        self._service_client = self._build_service_client()
        self._container_client = self._service_client.get_container_client(self.container)
        self._content_settings = ContentSettings(content_type="audio/wav")

        if settings.azure_storage_connection_string:
            try:
                self._container_client.create_container(public_access=PublicAccess.Blob)
                logger.info(f"Created Azure blob container: {self.container}")
            except ResourceExistsError:
                logger.info(f"Using existing Azure blob container: {self.container}")
        else:
            # Managed identity is usually scoped to the data plane of a container
            # someone else provisioned, and accounts with identity access tend to
            # forbid public blobs. create_container would 403 rather than raise
            # ResourceExistsError, so only check that the container is reachable
            # and let a real misconfiguration fail here instead of on first upload.
            self._container_client.get_container_properties()
            logger.info(f"Using Azure blob container via managed identity: {self.container}")

    @staticmethod
    def _build_service_client():
        """Pick the credential from config: account key / Azurite, or managed identity."""
        from azure.storage.blob import BlobServiceClient

        if settings.azure_storage_connection_string:
            return BlobServiceClient.from_connection_string(settings.azure_storage_connection_string)
        if settings.azure_storage_account_url:
            from azure.identity import DefaultAzureCredential

            return BlobServiceClient(settings.azure_storage_account_url, credential=DefaultAzureCredential())
        raise ValueError(
            "Azure Blob not configured. Set AZURE_STORAGE_CONNECTION_STRING (account key or "
            "Azurite) or AZURE_STORAGE_ACCOUNT_URL (managed identity)."
        )

    def uses_remote_storage(self) -> bool:
        return True

    def get_file_path(self, session_id: str, filename: str) -> str:
        return f"{session_id}/{filename}"

    def upload_file(self, local_path: str, storage_path: str) -> bool:
        from azure.core.exceptions import AzureError

        try:
            blob_client = self._container_client.get_blob_client(storage_path)
            with open(local_path, "rb") as data:
                blob_client.upload_blob(
                    data,
                    overwrite=True,
                    content_settings=self._content_settings,
                )
            logger.info(f"Uploaded to Azure Blob: {self.container}/{storage_path}")
            return True
        except (OSError, AzureError) as e:
            logger.error(f"Failed to upload to Azure Blob {storage_path}: {e}")
            return False

    def get_webhook_file_location(self, storage_path: str) -> str:
        if self._public_endpoint:
            return f"{self._public_endpoint}/{self.container}/{storage_path}"
        return f"{self.container}/{storage_path}"


@lru_cache(maxsize=1)
def get_storage() -> StorageBackend:
    """
    Get the configured storage backend, building it on first use.

    Built lazily and cached: the remote backends do network I/O in __init__
    (bucket/container creation), so constructing this at import time would make
    a misconfigured MinIO or Azure break the whole app's import rather than just
    the recordings that need it.
    """
    backend = settings.storage_backend.lower()
    if backend == "minio":
        logger.info("Using MinIO storage backend")
        return MinIOStorage()
    if backend in ("azure", "blob"):
        logger.info("Using Azure Blob storage backend")
        return AzureBlobStorage()
    logger.info("Using local filesystem storage backend")
    return LocalStorage()
