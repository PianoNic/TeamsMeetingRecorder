"""Which Azure client gets built for each credential config.

Run: python -m pytest tests/   or   python tests/test_azure_credentials.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.storage import AzureBlobStorage


def _configure(connection_string=None, account_url=None):
    settings.azure_storage_connection_string = connection_string
    settings.azure_storage_account_url = account_url


def test_connection_string_uses_shared_key():
    _configure(connection_string="UseDevelopmentStorage=true")
    client = AzureBlobStorage._build_service_client()
    assert type(client.credential).__name__ == "SharedKeyCredentialPolicy"
    assert client.url.startswith("http://127.0.0.1:10000/")


def test_connection_string_wins_over_account_url():
    _configure(connection_string="UseDevelopmentStorage=true", account_url="https://x.blob.core.windows.net/")
    assert type(AzureBlobStorage._build_service_client().credential).__name__ == "SharedKeyCredentialPolicy"


def test_account_url_uses_managed_identity():
    from azure.identity import DefaultAzureCredential

    _configure(account_url="https://x.blob.core.windows.net/")
    client = AzureBlobStorage._build_service_client()
    assert isinstance(client.credential, DefaultAzureCredential)
    assert client.url == "https://x.blob.core.windows.net/"


def test_neither_raises_naming_both():
    _configure()
    try:
        AzureBlobStorage._build_service_client()
    except ValueError as e:
        assert "AZURE_STORAGE_CONNECTION_STRING" in str(e) and "AZURE_STORAGE_ACCOUNT_URL" in str(e)
    else:
        raise AssertionError("expected ValueError")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
