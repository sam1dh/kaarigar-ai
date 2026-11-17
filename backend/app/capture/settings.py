"""Phase 2 settings. Reads the same .env as the rest of the backend.

If you prefer, move these fields into app/core/config.py's Settings and import them from there.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class CaptureSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    APP_ENV: str = "development"
    DATABASE_URL: str = ""

    # Sarvam speech-to-text
    SARVAM_API_KEY: str = ""
    SARVAM_STT_MODEL: str = "saaras:v3"      # `mode` only works with saaras:v3
    SARVAM_STT_MODE: str = "translate"       # any Indian language -> English text
    SARVAM_TIMEOUT_SEC: float = 60.0

    # Groq LLMs
    GROQ_API_KEY: str = ""
    GROQ_MODEL_SMALL: str = "openai/gpt-oss-20b"    # extraction, translation
    GROQ_MODEL_LARGE: str = "openai/gpt-oss-120b"   # AI check
    GROQ_TIMEOUT_SEC: float = 45.0

    # Recording limits
    MAX_RECORDING_SEC: int = 180
    MIN_RECORDING_SEC: float = 2.0
    MAX_AUDIO_MB: float = 10.0
    STT_SEGMENT_SEC: int = 25               # Sarvam REST is meant for clips under 30 s

    # Pipeline
    TAXONOMY_MATCH_MIN: float = 0.55        # pg_trgm similarity to reuse an existing symptom/cause/fix
    CAPTURE_WORKERS: int = 2                # parallel capture runs (keeps Groq free-tier happy)
    CHECK_MANUAL_CONTEXT: int = 3           # manual excerpts given to the AI check

    @property
    def is_dev(self) -> bool:
        return self.APP_ENV.lower() == "development"


@lru_cache
def get_capture_settings() -> CaptureSettings:
    return CaptureSettings()
