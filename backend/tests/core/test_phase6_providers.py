"""Phase 6: provider order, fallthrough, breaker, STT/TTS chains and the answer cache."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from app.core.answer_cache import chunk_key, machine_key, normalize_question, question_key
from app.core.breaker import CircuitBreaker
from app.core.llm_chain import ChainStructured, LLMChainWriter
from app.core.openai_compat import ProviderError
from app.core.provider_config import (
    LLMProvider,
    STTProvider,
    TTSProvider,
    llm_candidates,
    key_enabled,
    stt_candidates,
    tts_candidates,
)
from app.core.stt_chain import STTChain, STTUnavailable
from app.core.tts_chain import TTSChain, TTSUnavailable

GROQ120 = LLMProvider("groq", "https://api.groq.com/openai/v1", "k", "openai/gpt-oss-120b", True)
GROQ20 = LLMProvider("groq", "https://api.groq.com/openai/v1", "k", "openai/gpt-oss-20b", True)
MISTRAL = LLMProvider("mistral", "https://api.mistral.ai/v1", "m", "mistral-small-latest", False)


# --------------------------------------------------------------------------- settings
def cfg(**kw):
    base = dict(
        GROQ_API_KEY="g", GROQ_MODEL_ANSWER="openai/gpt-oss-120b", GROQ_MODEL_SMALL="openai/gpt-oss-20b",
        MISTRAL_API_KEY="m", MISTRAL_MODEL="mistral-small-latest", GEMINI_API_KEY="x",
        GEMINI_MODEL="gemini-2.5-flash", OPENROUTER_API_KEY="", OPENROUTER_MODEL="or-model",
        SARVAM_API_KEY="s", SARVAM_STT_MODEL="saaras:v3", SARVAM_STT_MODE="translate",
        AZURE_SPEECH_KEY="a", AZURE_SPEECH_REGION="centralindia", DEEPGRAM_API_KEY="",
        GROQ_STT_MODEL="whisper-large-v3", SARVAM_TTS_MODEL="bulbul:v3", SARVAM_TTS_SPEAKER="shubh",
        DISABLE_PROVIDERS="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_key_enabled_rejects_placeholders_and_blanks():
    assert key_enabled("sk-real")
    assert not key_enabled("PASTE_GROQ_KEY")
    assert not key_enabled("  ")
    assert not key_enabled(None)


def test_llm_order_is_groq_120_groq_20_mistral_gemini():
    names = [(p.name, p.model) for p in llm_candidates(cfg())]
    assert names == [
        ("groq", "openai/gpt-oss-120b"),
        ("groq", "openai/gpt-oss-20b"),
        ("mistral", "mistral-small-latest"),
        ("gemini", "gemini-2.5-flash"),
    ]


def test_openrouter_only_with_a_key_and_disable_skips_provider():
    assert [p.name for p in llm_candidates(cfg())][-1] == "gemini"
    with_or = llm_candidates(cfg(OPENROUTER_API_KEY="or"))
    assert with_or[-1].name == "openrouter"
    without_groq = llm_candidates(cfg(DISABLE_PROVIDERS="groq"))
    assert [p.name for p in without_groq] == ["mistral", "gemini"]
    placeholders = llm_candidates(cfg(GEMINI_API_KEY="PASTE_GEMINI"))
    assert "gemini" not in [p.name for p in placeholders]


def test_stt_order_and_deepgram_key_gate():
    assert [p.name for p in stt_candidates(cfg())] == ["sarvam", "groq", "azure"]
    assert [p.name for p in stt_candidates(cfg(DEEPGRAM_API_KEY="d"))] == [
        "sarvam", "groq", "azure", "deepgram"]


def test_tts_order_and_final_browser_when_no_keys():
    assert [p.name for p in tts_candidates(cfg())] == ["sarvam", "azure"]
    assert tts_candidates(cfg(SARVAM_API_KEY="", AZURE_SPEECH_KEY="")) == []


# --------------------------------------------------------------------------- writer chain
class FakeLLMClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[str] = []

    def stream_chat(self, provider, messages, **kw):
        self.calls.append(f"{provider.name}:{provider.model}")
        action = self.script.pop(0)
        if isinstance(action, Exception):
            raise action
        yield from action

    def chat(self, provider, messages, **kw):
        self.calls.append(f"{provider.name}:{provider.model}")
        action = self.script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


def test_writer_falls_through_429_413_5xx_timeout_in_order():
    err429 = ProviderError("groq", status=429, kind="http")
    err413 = ProviderError("groq", status=413, kind="http")
    err500 = ProviderError("mistral", status=503, kind="http")
    err_timeout = ProviderError("gemini", kind="timeout")
    client = FakeLLMClient([err429, err413, err500, err_timeout, ["final answer [E1]"]])
    providers = [GROQ120, GROQ20, MISTRAL, LLMProvider("gemini", "g", "k", "gem", False),
                 LLMProvider("openrouter", "o", "k", "or-model", True)]
    w = LLMChainWriter(providers, client=client, error_factory=lambda: RuntimeError("down"))
    out = "".join(w.stream(system="s", user="u"))
    assert out == "final answer [E1]"
    assert client.calls == ["groq:openai/gpt-oss-120b", "groq:openai/gpt-oss-20b",
                            "mistral:mistral-small-latest", "gemini:gem", "openrouter:or-model"]


def test_writer_breaker_opens_after_three_failures_and_skips_calls():
    err = ProviderError("groq", status=500, kind="http")
    client = FakeLLMClient([err, err, err, err, err, err])
    breaker = CircuitBreaker(failures=3, cooldown_sec=60)
    w = LLMChainWriter([GROQ120], breaker=breaker, client=client, error_factory=lambda: RuntimeError("down"))
    for _ in range(3):
        with pytest.raises(RuntimeError):
            list(w.stream(system="s", user="u"))
    assert len(client.calls) == 3
    with pytest.raises(RuntimeError):
        list(w.stream(system="s", user="u"))
    assert len(client.calls) == 3               # breaker skipped, no network call


def test_breaker_allows_again_after_cooldown():
    now = [1000.0]
    b = CircuitBreaker(failures=3, cooldown_sec=60, clock=lambda: now[0])
    for _ in range(3):
        b.failure("groq")
    assert not b.allow("groq")
    now[0] += 61
    assert b.allow("groq")


def test_invalid_citations_are_discarded_before_any_text_reaches_the_user():
    client = FakeLLMClient([["no citation here"], ["1. Fit the gauge [E1]"]])
    w = LLMChainWriter([GROQ120, MISTRAL], client=client, error_factory=lambda: RuntimeError("down"))
    validate = lambda text: "[E1]" in text           # noqa: E731
    out = list(w.stream(system="s", user="u", validate=validate,
                        flush_when=lambda buf: "[E1]" in buf))
    assert out == ["1. Fit the gauge [E1]"]
    assert len(client.calls) == 2


def test_text_returns_none_when_every_provider_fails():
    client = FakeLLMClient([ProviderError("groq", status=500), ProviderError("mistral", status=401)])
    w = LLMChainWriter([GROQ120, MISTRAL], client=client)
    assert w.text(system="s", user="u") is None


# --------------------------------------------------------------------------- structured chain
class Out(BaseModel):
    value: str


SCHEMA = {"type": "object", "additionalProperties": False, "required": ["value"],
          "properties": {"value": {"type": "string"}}}


def test_structured_400_falls_back_to_json_object_then_succeeds():
    client = FakeLLMClient([ProviderError("groq", status=400), '{"value":"ok"}'])
    s = ChainStructured([GROQ120], client=client, error_factory=lambda: RuntimeError("down"))
    assert s.structured(system="s", user="u", schema_name="x", schema=SCHEMA, out=Out).value == "ok"
    assert len(client.calls) == 2


def test_structured_falls_through_to_next_provider_and_strips_fences():
    client = FakeLLMClient([ProviderError("groq", status=500), '```json\n{"value":"m"}\n```'])
    s = ChainStructured([GROQ120, MISTRAL], client=client, error_factory=lambda: RuntimeError("down"))
    assert s.structured(system="s", user="u", schema_name="x", schema=SCHEMA, out=Out).value == "m"


def test_structured_all_providers_fail():
    client = FakeLLMClient([ProviderError("groq", status=500), ProviderError("mistral", status=500)])
    s = ChainStructured([GROQ120, MISTRAL], client=client, error_factory=lambda: RuntimeError("down"))
    with pytest.raises(RuntimeError):
        s.structured(system="s", user="u", schema_name="x", schema=SCHEMA, out=Out)


# --------------------------------------------------------------------------- STT chain
class FakeResponse:
    def __init__(self, status=200, json_body=None, content=b""):
        self.status_code = status
        self._json = json_body or {}
        self.content = content

    def json(self):
        return self._json


class FakeHTTP:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[str] = []

    def post(self, url, **kw):
        self.calls.append(url)
        action = self.script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


SARVAM = STTProvider("sarvam", "sarvam", "k", "https://api.sarvam.ai", "saaras:v3", "codemix")
GROQ_STT = STTProvider("groq", "groq", "k", "https://api.groq.com/openai/v1", "whisper-large-v3")
AZURE_STT = STTProvider("azure", "azure", "k", "https://x.stt.speech.microsoft.com/speech/recognition",
                        region="x")


def test_stt_falls_back_sarvam_groq_azure():
    http = FakeHTTP([FakeResponse(403), FakeResponse(500),
                     FakeResponse(200, {"RecognitionStatus": "Success", "DisplayText": "pump noisy"})])
    chain = STTChain([SARVAM, GROQ_STT, AZURE_STT], http=http)
    out = chain.transcribe_segments([b"wav"], "hi-IN")
    assert out.transcript == "pump noisy"
    assert len(http.calls) == 3 and "speech.microsoft.com" in http.calls[-1]


def test_stt_all_fail_raises_mapped_error():
    http = FakeHTTP([FakeResponse(403), FakeResponse(500), FakeResponse(500)])
    chain = STTChain([SARVAM, GROQ_STT, AZURE_STT], http=http, error_factory=lambda: RuntimeError("stt"))
    with pytest.raises(RuntimeError):
        chain.transcribe_segments([b"wav"])


def test_stt_deepgram_only_used_when_configured():
    assert stt_candidates(cfg())[-1].name == "azure"
    assert stt_candidates(cfg(DEEPGRAM_API_KEY="d"))[-1].name == "deepgram"


# --------------------------------------------------------------------------- TTS chain
SARVAM_TTS = TTSProvider("sarvam", "sarvam", "k", model="bulbul:v3", speaker="shubh")
AZURE_TTS = TTSProvider("azure", "azure", "k", region="centralindia")


def test_tts_falls_back_to_azure_neural_voice():
    http = FakeHTTP([FakeResponse(500), FakeResponse(200, content=b"RIFFazure")])
    chain = TTSChain([SARVAM_TTS, AZURE_TTS], http=http)
    assert chain.synthesize("hello", "hi-IN") == b"RIFFazure"


def test_tts_all_fail_raises_so_router_can_use_browser():
    http = FakeHTTP([FakeResponse(500), FakeResponse(403)])
    chain = TTSChain([SARVAM_TTS, AZURE_TTS], http=http, error_factory=lambda: RuntimeError("tts"))
    with pytest.raises(RuntimeError):
        chain.synthesize("hello", "hi-IN")


def test_tts_with_no_providers_raises_for_browser_fallback():
    chain = TTSChain([], error_factory=lambda: RuntimeError("browser"))
    with pytest.raises(RuntimeError):
        chain.synthesize("hello", "hi-IN")


# --------------------------------------------------------------------------- cache keys
def test_cache_question_key_is_stable_across_case_and_punctuation():
    a = question_key("Pressure NOT building on HP-07?")
    b = question_key("pressure not building on hp 07")
    assert a == b
    assert normalize_question("  Pump,  NOISE! ") == "pump noise"


def test_cache_machine_and_chunk_keys():
    assert machine_key(None) == "any"
    assert machine_key({"code": "hp-07", "model": "HPX-200"}) == "HP-07|HPX-200"
    one = chunk_key([{"chunk_id": "a"}, {"chunk_id": "b"}])
    two = chunk_key([{"chunk_id": "b"}, {"chunk_id": "a"}])
    assert one != two
    assert chunk_key([{"source_type": "manual", "source_id": "x", "page": 2}]) == \
        chunk_key([{"source_type": "manual", "source_id": "x", "page": 2}])
