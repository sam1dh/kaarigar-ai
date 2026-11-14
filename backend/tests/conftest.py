"""Test setup: load the repo-root .env so integration tests can use Supabase."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Settings reads .env relative to CWD; pytest runs from backend/. Point it at the repo root.
os.environ.setdefault("PYTEST_REPO_ROOT", str(REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
except ImportError:  # pragma: no cover — dotenv ships with pydantic-settings
    pass
