"""How the S3 client is built for each provider setting.

Run: python -m pytest tests/   or   python tests/test_s3_storage.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.storage import S3Storage, get_storage


def _configure(endpoint=None, region=None, path_style=False):
    settings.s3_endpoint_url = endpoint
    settings.s3_region = region
    settings.s3_access_key_id = "key"
    settings.s3_secret_access_key = "secret"
    settings.s3_force_path_style = path_style


def test_no_endpoint_means_aws():
    _configure(region="eu-central-1")
    client = S3Storage._build_client()
    assert client.meta.endpoint_url == "https://s3.eu-central-1.amazonaws.com"


def test_endpoint_points_at_another_provider():
    _configure(endpoint="https://abc.r2.cloudflarestorage.com", region="auto")
    assert S3Storage._build_client().meta.endpoint_url == "https://abc.r2.cloudflarestorage.com"


def test_path_style_for_self_hosted_servers():
    _configure(endpoint="http://s3.internal:9000", path_style=True)
    assert S3Storage._build_client().meta.config.s3["addressing_style"] == "path"


def test_webhook_location_without_and_with_public_endpoint():
    storage = S3Storage.__new__(S3Storage)
    storage.bucket = "recordings"
    settings.s3_public_endpoint = None
    assert storage.get_webhook_file_location("s1/a.flac") == "recordings/s1/a.flac"
    settings.s3_public_endpoint = "https://cdn.example.com/recordings/"
    assert storage.get_webhook_file_location("s1/a.flac") == "https://cdn.example.com/recordings/s1/a.flac"
    settings.s3_public_endpoint = None


def test_removed_minio_backend_fails_loudly():
    # Falling back to local would keep recordings inside the container without a word.
    settings.storage_backend = "minio"
    get_storage.cache_clear()
    try:
        with pytest.raises(ValueError, match="STORAGE_BACKEND=s3"):
            get_storage()
    finally:
        settings.storage_backend = "local"
        get_storage.cache_clear()


def test_a_leftover_removed_setting_does_not_stop_startup(tmp_path):
    from app.config import Settings

    env = tmp_path / ".env"
    env.write_text("MINIO_ENDPOINT=minio.example.com:9000\nS3_BUCKET=kept\n", encoding="utf-8")
    assert Settings(_env_file=env).s3_bucket == "kept"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
