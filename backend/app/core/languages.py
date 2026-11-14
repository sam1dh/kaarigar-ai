"""Load shared/languages.json — the single source of truth for language support.

Resolution order for the file location:
  1. LANGUAGES_FILE env (see .env.example)
  2. the first shared/languages.json found walking up from this file
     (works both in the repo and inside the Docker image)
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel


class Language(BaseModel):
    code: str
    name: str
    native: str
    region: str
    script: str
    enabled: bool
    stt: bool
    tts: bool


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    from app.core.config import get_settings

    env = os.environ.get("LANGUAGES_FILE", "").strip() or get_settings().languages_file
    if env:
        paths.append(Path(env))
    # parents: core → app → backend → repo root (dev)  /  core → app → /app (container)
    paths.extend(p / "shared" / "languages.json" for p in Path(__file__).resolve().parents)
    return paths


@lru_cache
def load() -> dict:
    """{"default": <code>, "languages": [Language, ...]} — raises if the file is missing."""
    for path in _candidate_paths():
        if path.is_file():
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            languages = [Language(**item) for item in raw["languages"]]
            return {"default": raw.get("default", "en-IN"), "languages": languages}
    raise RuntimeError(
        "shared/languages.json not found — set LANGUAGES_FILE or keep shared/ next to backend/"
    )


def default_code() -> str:
    return load()["default"]


def all_codes() -> list[str]:
    return [lang.code for lang in load()["languages"]]


def enabled_languages() -> list[Language]:
    return [lang for lang in load()["languages"] if lang.enabled]


def enabled_codes() -> list[str]:
    return [lang.code for lang in enabled_languages()]


def get_language(code: str) -> Language | None:
    return next((lang for lang in load()["languages"] if lang.code == code), None)


def is_enabled(code: str) -> bool:
    lang = get_language(code)
    return bool(lang and lang.enabled)
