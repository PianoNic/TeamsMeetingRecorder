"""Storage backend abstraction for recordings."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

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
    def download_file(self, storage_path: str, local_path: str) -> bool:
        """Download a file from storage. Returns True on success."""
        pass

    @abstractmethod
    def delete_file(self, storage_path: str) -> bool:
        """Delete a file from storage. Returns True on success."""
        pass

    @abstractmethod
    def file_exists(self, storage_path: str) -> bool:
        """Check if a file exists in storage."""
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

    def download_file(self, storage_path: str, local_path: str) -> bool:
        """For local storage, just verify file exists."""
        return Path(storage_path).exists()

    def delete_file(self, storage_path: str) -> bool:
        """Delete a local file."""
        try:
            Path(storage_path).unlink(missing_ok=True)
            logger.info(f"Deleted local file: {storage_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete local file {storage_path}: {e}")
            return False

    def file_exists(self, storage_path: str) -> bool:
        """Check if local file exists."""
        return Path(storage_path).exists()

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

    def download_file(self, storage_path: str, local_path: str) -> bool:
        """Download a file from MinIO."""
        try:
            self.client.fget_object(
                bucket_name=self.bucket,
                object_name=storage_path,
                file_path=local_path,
            )
            logger.info(f"Downloaded from MinIO: {storage_path}")
            return True
        except S3Error as e:
            logger.error(f"Failed to download from MinIO {storage_path}: {e}")
            return False

    def delete_file(self, storage_path: str) -> bool:
        """Delete a file from MinIO."""
        try:
            self.client.remove_object(
                bucket_name=self.bucket,
                object_name=storage_path,
            )
            logger.info(f"Deleted from MinIO: {storage_path}")
            return True
        except S3Error as e:
            logger.error(f"Failed to delete from MinIO {storage_path}: {e}")
            return False

    def file_exists(self, storage_path: str) -> bool:
        """Check if file exists in MinIO."""
        try:
            self.client.stat_object(
                bucket_name=self.bucket,
                object_name=storage_path,
            )
            return True
        except S3Error:
            return False

    def get_webhook_file_location(self, storage_path: str) -> str:
        protocol = "https" if settings.minio_secure else "http"
        return f"{protocol}://{settings.minio_endpoint}/{self.bucket}/{storage_path}"


class AzureBlobStorage(StorageBackend):
    """Azure Blob Storage backend (production or Azurite emulator)."""

    def __init__(self):
        from azure.core.exceptions import ResourceExistsError
        from azure.storage.blob import BlobServiceClient, ContentSettings, PublicAccess

        if not settings.azure_storage_connection_string:
            raise ValueError(
                "Azure Blob not configured. Set AZURE_STORAGE_CONNECTION_STRING "
                "(use Azurite dev connection string locally)."
            )

        self.container = settings.azure_storage_container
        self._public_endpoint = (settings.azure_storage_public_endpoint or "").rstrip("/")
        self._service_client = BlobServiceClient.from_connection_string(
            settings.azure_storage_connection_string
        )
        self._container_client = self._service_client.get_container_client(self.container)
        self._content_settings = ContentSettings(content_type="audio/wav")

        try:
            self._container_client.create_container(public_access=PublicAccess.Blob)
            logger.info(f"Created Azure blob container: {self.container}")
        except ResourceExistsError:
            logger.info(f"Using existing Azure blob container: {self.container}")

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

    def download_file(self, storage_path: str, local_path: str) -> bool:
        from azure.core.exceptions import AzureError

        try:
            blob_client = self._container_client.get_blob_client(storage_path)
            with open(local_path, "wb") as file:
                file.write(blob_client.download_blob().readall())
            logger.info(f"Downloaded from Azure Blob: {storage_path}")
            return True
        except AzureError as e:
            logger.error(f"Failed to download from Azure Blob {storage_path}: {e}")
            return False

    def delete_file(self, storage_path: str) -> bool:
        from azure.core.exceptions import AzureError

        try:
            self._container_client.delete_blob(storage_path)
            logger.info(f"Deleted from Azure Blob: {storage_path}")
            return True
        except AzureError as e:
            logger.error(f"Failed to delete from Azure Blob {storage_path}: {e}")
            return False

    def file_exists(self, storage_path: str) -> bool:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self._container_client.get_blob_client(storage_path).get_blob_properties()
            return True
        except ResourceNotFoundError:
            return False

    def get_webhook_file_location(self, storage_path: str) -> str:
        if self._public_endpoint:
            return f"{self._public_endpoint}/{self.container}/{storage_path}"
        return f"{self.container}/{storage_path}"


def get_storage_backend() -> StorageBackend:
    """
    Factory function to get the configured storage backend.

    Returns:
        StorageBackend instance based on settings.storage_backend
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


# Global storage instance
storage = get_storage_backend()
