"""Phase 3 settings. Reads the same .env as the rest of the backend."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AssistSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    APP_ENV: str = "development"

    # Keys (same as Phase 2) + Phase 6 fallbacks
    SARVAM_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""
    MISTRAL_MODEL: str = "mistral-small-latest"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    OPENROUTER_API_KEY: str = ""              # only used when set
    OPENROUTER_MODEL: str = "openai/gpt-oss-120b"
    AZURE_SPEECH_KEY: str = ""
    AZURE_SPEECH_REGION: str = ""
    DEEPGRAM_API_KEY: str = ""                # only used when set
    DEEPGRAM_STT_MODEL: str = "nova-3"
    GROQ_STT_MODEL: str = "whisper-large-v3"
    DISABLE_PROVIDERS: str = ""               # e.g. "groq" for a fallback drill

    # Speech-to-text for questions: keep the technician's own words for "You asked"
    SARVAM_STT_MODEL: str = "saaras:v3"
    ASSIST_STT_MODE: str = "codemix"          # Indic words in their script, English words (HP-07, filter) in English
    SARVAM_TIMEOUT_SEC: float = 60.0

    # Text-to-speech (read aloud). Browser voices are used first; this is the fallback.
    SARVAM_TTS_MODEL: str = "bulbul:v3"
    SARVAM_TTS_SPEAKER: str = "shubh"
    TTS_MAX_CHARS: int = 2500                  # bulbul:v3 accepts up to 2500 characters per request

    # Groq
    GROQ_MODEL_ANSWER: str = "openai/gpt-oss-120b"   # writes the answer (streamed)
    GROQ_MODEL_SMALL: str = "openai/gpt-oss-20b"     # question -> English, answer -> English, fallback writer
    GROQ_TIMEOUT_SEC: float = 45.0
    LLM_TIMEOUT_SEC: float = 8.0              # per provider, before the next one is tried
    PROVIDER_BREAKER_FAILURES: int = 3
    PROVIDER_BREAKER_COOLDOWN_SEC: float = 60.0
    ANSWER_MAX_TOKENS: int = 700              # token saving: shorter, still complete answers

    # Questions
    MAX_QUESTION_SEC: int = 60
    MIN_QUESTION_SEC: float = 1.0
    MAX_QUESTION_CHARS: int = 500
    # Separate from Phase 2's MAX_AUDIO_MB: repair notes allow 10 MB, questions 5 MB.
    ASSIST_MAX_AUDIO_MB: float = 5.0
    AUDIO_CLEAN: bool = True          # server-side noise filter + silence trim before Sarvam
    MIN_SPEECH_SEC: float = 0.4       # less speech than this after trimming -> "no_speech" (no Sarvam call)
    STT_SEGMENT_SEC: int = 25

    # Search + answer
    SEARCH_K: int = 8                 # results asked from Phase 1 search
    CONTEXT_K: int = 4                # sources given to the writer (token saving)
    SOURCE_CHARS: int = 700           # characters per source in the prompt
    MIN_SCORE_RATIO: float = 0.35     # drop chunks scoring below this fraction of the best result
    ESCALATE_BELOW: float = 0.5       # confidence below this -> the app suggests asking an expert

    # Answer cache (Postgres). Only grounded answers are stored.
    ANSWER_CACHE: bool = True
    ANSWER_CACHE_TTL_DAYS: int = 7

    # Capacity (Groq free tier is small)
    ASSIST_WORKERS: int = 4           # questions answered at the same time; more wait in a queue
    ASK_PER_MINUTE: int = 10          # per person
    TTS_PER_MINUTE: int = 20          # per person
    SSE_PING_SEC: float = 10.0        # keep-alive comment so proxies don't close a quiet stream

    @property
    def is_dev(self) -> bool:
        return self.APP_ENV.lower() == "development"


@lru_cache
def get_assist_settings() -> AssistSettings:
    return AssistSettings()
