"""The API reference on the docs site is generated from docs/public/openapi.json.

This fails when that file no longer matches the code, so a changed endpoint cannot ship with an
outdated reference. Refresh it as described in docs/development.md.

Run: python -m pytest tests/
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app

PUBLISHED = Path(__file__).resolve().parent.parent / "docs" / "public" / "openapi.json"


def _without_version(schema: dict) -> dict:
    # The version moves with every release (application.properties); the reference does not
    # need a commit for that.
    schema = json.loads(json.dumps(schema))
    schema["info"].pop("version", None)
    return schema


def test_published_schema_matches_the_api():
    published = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    assert _without_version(published) == _without_version(app.openapi()), (
        "docs/public/openapi.json is out of date, refresh it (see docs/development.md)"
    )
