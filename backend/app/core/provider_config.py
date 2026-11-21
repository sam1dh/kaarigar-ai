"""Provider order and enablement for Phase 6 fallbacks.

One place decides which AI providers are usable. A key counts as present only
when it is non-empty and does not start with ``PASTE_`` (the placeholder used in
the deployment examples). ``DISABLE_PROVIDERS=groq,mistral`` turns providers off
without deleting their keys, which is how the production fallback is verified.

Nothing here logs or returns an API key.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

GROQ_BASE = "https://api.groq.com/openai/v1"
MISTRAL_BASE = "https://api.mistral.ai/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

SARVAM_BASE = "https://api.sarvam.ai"
DEEPGRAM_BASE = "https://api.deepgram.com/v1"
AZURE_SPEECH_STT = "https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
AZURE_SPEECH_TTS = "https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"


def key_enabled(key: str | None) -> bool:
    """A key is usable when it is set and is not a ``PASTE_...`` placeholder."""
    k = (key or "").strip()
    return bool(k) and not k.upper().startswith("PASTE_")


def disabled_providers(raw: str | None) -> set[str]:
    return {p.strip().lower() for p in (raw or "").split(",") if p.strip()}


def _cfg(settings: Any, name: str, default: Any = "") -> Any:
    return getattr(settings, name, default)


@dataclass(frozen=True)
class LLMProvider:
    name: str
    base_url: str
    api_key: str
    model: str
    supports_schema: bool = True


@dataclass(frozen=True)
class STTProvider:
    name: str
    kind: str                 # sarvam | groq | azure | deepgram
    api_key: str
    base_url: str = ""
    model: str = ""
    mode: str = "translate"
    region: str = ""


@dataclass(frozen=True)
class TTSProvider:
    name: str
    kind: str                 # sarvam | azure
    api_key: str
    region: str = ""
    model: str = "bulbul:v3"
    speaker: str = "shubh"


def llm_candidates(settings: Any) -> list[LLMProvider]:
    """Required order: Groq 120b, Groq 20b, Mistral, Gemini, OpenRouter (only if keyed)."""
    off = disabled_providers(_cfg(settings, "DISABLE_PROVIDERS"))
    out: list[LLMProvider] = []

    groq_key = _cfg(settings, "GROQ_API_KEY")
    if key_enabled(groq_key) and "groq" not in off:
        for model in (_cfg(settings, "GROQ_MODEL_ANSWER", "openai/gpt-oss-120b"),
                      _cfg(settings, "GROQ_MODEL_SMALL", "openai/gpt-oss-20b")):
            if model:
                out.append(LLMProvider("groq", GROQ_BASE, groq_key, model, True))

    mistral_key = _cfg(settings, "MISTRAL_API_KEY")
    if key_enabled(mistral_key) and "mistral" not in off:
        out.append(LLMProvider("mistral", MISTRAL_BASE, mistral_key,
                               _cfg(settings, "MISTRAL_MODEL", "mistral-small-latest"), False))

    gemini_key = _cfg(settings, "GEMINI_API_KEY")
    if key_enabled(gemini_key) and "gemini" not in off:
        out.append(LLMProvider("gemini", GEMINI_BASE.rstrip("/") + "/", gemini_key,
                               _cfg(settings, "GEMINI_MODEL", "gemini-2.5-flash"), False))

    openrouter_key = _cfg(settings, "OPENROUTER_API_KEY")
    if key_enabled(openrouter_key) and "openrouter" not in off:
        out.append(LLMProvider("openrouter", OPENROUTER_BASE, openrouter_key,
                               _cfg(settings, "OPENROUTER_MODEL", "openai/gpt-oss-120b"), True))
    return out


def stt_candidates(settings: Any) -> list[STTProvider]:
    """Sarvam -> Groq Whisper -> Azure Speech F0 -> Deepgram (only if a key is set)."""
    off = disabled_providers(_cfg(settings, "DISABLE_PROVIDERS"))
    out: list[STTProvider] = []

    sarvam_key = _cfg(settings, "SARVAM_API_KEY")
    if key_enabled(sarvam_key) and "sarvam" not in off:
        out.append(STTProvider("sarvam", "sarvam", sarvam_key, SARVAM_BASE,
                               _cfg(settings, "SARVAM_STT_MODEL", "saaras:v3"),
                               _cfg(settings, "SARVAM_STT_MODE", "translate")))

    groq_key = _cfg(settings, "GROQ_API_KEY")
    if key_enabled(groq_key) and "groq" not in off:
        out.append(STTProvider("groq", "groq", groq_key, GROQ_BASE,
                               _cfg(settings, "GROQ_STT_MODEL", "whisper-large-v3")))

    azure_key = _cfg(settings, "AZURE_SPEECH_KEY")
    azure_region = (_cfg(settings, "AZURE_SPEECH_REGION") or "").strip()
    if key_enabled(azure_key) and azure_region and "azure" not in off:
        out.append(STTProvider("azure", "azure", azure_key,
                               AZURE_SPEECH_STT.format(region=azure_region), region=azure_region))

    deepgram_key = _cfg(settings, "DEEPGRAM_API_KEY")
    if key_enabled(deepgram_key) and "deepgram" not in off:
        out.append(STTProvider("deepgram", "deepgram", deepgram_key, DEEPGRAM_BASE,
                               _cfg(settings, "DEEPGRAM_STT_MODEL", "nova-3")))
    return out


def tts_candidates(settings: Any) -> list[TTSProvider]:
    """Sarvam Bulbul -> Azure Speech neural voice. Both missing/failed -> browser TTS."""
    off = disabled_providers(_cfg(settings, "DISABLE_PROVIDERS"))
    out: list[TTSProvider] = []

    sarvam_key = _cfg(settings, "SARVAM_API_KEY")
    if key_enabled(sarvam_key) and "sarvam" not in off:
        out.append(TTSProvider("sarvam", "sarvam", sarvam_key,
                               model=_cfg(settings, "SARVAM_TTS_MODEL", "bulbul:v3"),
                               speaker=_cfg(settings, "SARVAM_TTS_SPEAKER", "shubh")))

    azure_key = _cfg(settings, "AZURE_SPEECH_KEY")
    azure_region = (_cfg(settings, "AZURE_SPEECH_REGION") or "").strip()
    if key_enabled(azure_key) and azure_region and "azure" not in off:
        out.append(TTSProvider("azure", "azure", azure_key, region=azure_region))
    return out


# Azure neural voices used when Sarvam is unavailable. Keyed by the app's language codes.
AZURE_VOICES: dict[str, str] = {
    "hi-IN": "hi-IN-SwaraNeural",
    "mr-IN": "mr-IN-AarohiNeural",
    "ta-IN": "ta-IN-PallaviNeural",
    "te-IN": "te-IN-ShrutiNeural",
    "gu-IN": "gu-IN-DhwaniNeural",
    "kn-IN": "kn-IN-SapnaNeural",
    "ml-IN": "ml-IN-SobhanaNeural",
    "bn-IN": "bn-IN-TanishaaNeural",
    "pa-IN": "pa-IN-GurpreetNeural",
    "od-IN": "or-IN-SubhasiniNeural",
    "or-IN": "or-IN-SubhasiniNeural",
    "en-IN": "en-IN-NeerjaNeural",
}
