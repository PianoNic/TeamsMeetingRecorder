"""Shared test setup.

Settings reads `.env` from the working directory, so without this the results
would depend on whatever a developer happens to have configured locally - and a
key that Settings no longer declares makes the import fail outright, taking the
whole suite with it. Importing app.config from an empty directory pins the
defaults; the module caches its `settings` instance, so every later import in
the run gets the same clean object.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_cwd = os.getcwd()
with tempfile.TemporaryDirectory() as _empty:
    os.chdir(_empty)
    try:
        import app.config  # noqa: F401  (imported for its side effect)
    finally:
        os.chdir(_cwd)
