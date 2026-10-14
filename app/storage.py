"""Storage backend abstraction for recordings."""

import logging
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from app.config import settings, RECORDINGS_DIR, RECORDING_CONTENT_TYPES

logger = logging.getLogger(__name__)


def content_type_for(path: str) -> str:
    """The type of the file itself: a recording made under another RECORDING_FORMAT keeps its own."""
    return RECORDING_CONTENT_TYPES.get(Path(path).suffix.lstrip(".").lower(), "application/octet-stream")


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


class S3Storage(StorageBackend):
    """Any S3-compatible storage: AWS S3, Cloudflare R2, Hetzner, Wasabi, Backblaze B2, Ceph, ..."""

    def __init__(self):
        from botocore.exceptions import ClientError

        self.bucket = settings.s3_bucket
        self.client = self._build_client()
        try:
            self.client.head_bucket(Bucket=self.bucket)
            logger.info(f"Using existing S3 bucket: {self.bucket}")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket"):
                logger.error(f"Cannot reach S3 bucket {self.bucket}: {e}")
                raise
            # Created only when it is missing; keys scoped to one bucket usually
            # may not create buckets, so an existing one is the normal case.
            create = {"Bucket": self.bucket}
            if settings.s3_region and settings.s3_region != "us-east-1" and not settings.s3_endpoint_url:
                create["CreateBucketConfiguration"] = {"LocationConstraint": settings.s3_region}
            self.client.create_bucket(**create)
            logger.info(f"Created S3 bucket: {self.bucket}")

    @staticmethod
    def _build_client():
        import boto3
        from botocore.config import Config

        return boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region or None,
            # None lets boto3 use its default credential chain.
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
            config=Config(s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"}),
        )

    def uses_remote_storage(self) -> bool:
        return True

    def get_file_path(self, session_id: str, filename: str) -> str:
        """Get the object key (path in bucket)."""
        return f"{session_id}/{filename}"

    def upload_file(self, local_path: str, storage_path: str) -> bool:
        """Upload a file; large files go up in parts automatically."""
        from boto3.exceptions import S3UploadFailedError
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self.client.upload_file(
                local_path,
                self.bucket,
                storage_path,
                ExtraArgs={"ContentType": content_type_for(local_path)},
            )
            logger.info(f"Uploaded to S3: {storage_path}")
            return True
        except (BotoCoreError, ClientError, S3UploadFailedError) as e:
            logger.error(f"Failed to upload to S3 {storage_path}: {e}")
            return False

    def get_webhook_file_location(self, storage_path: str) -> str:
        if settings.s3_public_endpoint:
            return f"{settings.s3_public_endpoint.rstrip('/')}/{storage_path}"
        return f"{self.bucket}/{storage_path}"


class AzureBlobStorage(StorageBackend):
    """Azure Blob Storage backend (production or Azurite emulator)."""

    def __init__(self):
        from azure.core.exceptions import ResourceExistsError
        from azure.storage.blob import PublicAccess

        self.container = settings.azure_storage_container
        self._public_endpoint = (settings.azure_storage_public_endpoint or "").rstrip("/")
        self._service_client = self._build_service_client()
        self._container_client = self._service_client.get_container_client(self.container)

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
        from azure.storage.blob import ContentSettings

        try:
            blob_client = self._container_client.get_blob_client(storage_path)
            with open(local_path, "rb") as data:
                blob_client.upload_blob(
                    data,
                    overwrite=True,
                    content_settings=ContentSettings(content_type=content_type_for(local_path)),
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
    a misconfigured S3 or Azure break the whole app's import rather than just
    the recordings that need it.
    """
    backend = settings.storage_backend.lower()
    if backend == "s3":
        logger.info("Using S3 storage backend")
        return S3Storage()
    if backend == "minio":
        # Removed in favour of the generic S3 backend; falling back to local would
        # silently keep recordings inside the container.
        raise ValueError("STORAGE_BACKEND=minio was replaced by STORAGE_BACKEND=s3, see docs/configuration.md")
    if backend in ("azure", "blob"):
        logger.info("Using Azure Blob storage backend")
        return AzureBlobStorage()
    logger.info("Using local filesystem storage backend")
    return LocalStorage()
