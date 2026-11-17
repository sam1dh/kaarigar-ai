"""GroqLLM fallback behaviour and SarvamClient request/retry handling, without network."""
from types import SimpleNamespace

import groq
import httpx
import pytest

from app.capture.errors import CaptureError
from app.capture.llm import GroqLLM
from app.capture.sarvam import SarvamClient
from app.capture.schemas import EXTRACTION_SCHEMA, Extraction

GOOD = ('{"is_repair_note": true, "symptom": "pump noise", "cause": null, "fix": "top up oil", "steps": [], '
        '"parts": [], "tools": [], "safety_note": null, "downtime_min": 30, "missing": ["cause", "safety_note"]}')


def _resp(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _http_err(cls, status):
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return cls("x", response=httpx.Response(status, request=req, headers={"retry-after": "0"}), body=None)


class FakeCompletions:
    def __init__(self, script):
        self.script = list(script)
        self.kwargs = []

    def create(self, **kw):
        self.kwargs.append(kw)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return _resp(step)


def llm_with(script):
    comp = FakeCompletions(script)
    client = SimpleNamespace(chat=SimpleNamespace(completions=comp))
    return GroqLLM("", client=client), comp


def call(llm):
    return llm.structured(model="openai/gpt-oss-20b", system="s", user="u", schema_name="repair_record",
                          schema=EXTRACTION_SCHEMA, out=Extraction)


def test_strict_success():
    llm, comp = llm_with([GOOD])
    out = call(llm)
    assert out.symptom == "pump noise" and out.downtime_min == 30
    rf = comp.kwargs[0]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert comp.kwargs[0]["temperature"] == 0


def test_strict_400_falls_back_to_best_effort():
    llm, comp = llm_with([_http_err(groq.BadRequestError, 400), GOOD])
    assert call(llm).fix == "top up oil"
    assert comp.kwargs[1]["response_format"]["json_schema"]["strict"] is False


def test_invalid_json_then_valid():
    llm, comp = llm_with(['{"symptom": 5}', GOOD])
    assert call(llm).symptom == "pump noise"


def test_both_modes_bad_raises_capture_error():
    llm, _ = llm_with(["not json", "still not json"])
    with pytest.raises(CaptureError) as e:
        call(llm)
    assert e.value.code == "llm_failed"


def test_rate_limit_waits_once_then_succeeds():
    llm, comp = llm_with([_http_err(groq.RateLimitError, 429), GOOD])
    assert call(llm).symptom == "pump noise"
    assert comp.kwargs[1]["response_format"]["json_schema"]["strict"] is True   # same mode retried


def test_rate_limit_twice_gives_up():
    llm, _ = llm_with([_http_err(groq.RateLimitError, 429), _http_err(groq.RateLimitError, 429)])
    with pytest.raises(CaptureError):
        call(llm)


# --------------------------------------------------------------------- Sarvam

def sarvam_with(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url="https://api.sarvam.ai", transport=transport,
                        headers={"api-subscription-key": "k"})
    return SarvamClient("k", http=http)


def test_sarvam_request_and_join():
    seen = []

    def handler(req: httpx.Request):
        body = req.content.decode("latin-1")
        seen.append((req.url.path, req.headers.get("api-subscription-key"), body))
        n = len(seen)
        return httpx.Response(200, json={"request_id": f"r{n}", "transcript": f"part {n}.", "language_code": "mr-IN"})

    res = sarvam_with(handler).transcribe_segments([b"a", b"b"])
    assert res.transcript == "part 1. part 2." and res.language_code == "mr-IN" and res.request_ids == ["r1", "r2"]
    path, key, body = seen[0]
    assert path == "/speech-to-text" and key == "k"
    assert 'name="model"' in body and "saaras:v3" in body
    assert 'name="mode"' in body and "translate" in body
    assert "unknown" in body                     # language auto-detect


def test_sarvam_retries_429_then_ok():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": {"message": "slow down"}})
        return httpx.Response(200, json={"transcript": "ok fine done", "language_code": "hi-IN"})

    assert sarvam_with(handler).transcribe_segments([b"a"]).transcript == "ok fine done"
    assert calls["n"] == 2


def test_sarvam_403_is_stt_failed():
    def handler(req):
        return httpx.Response(403, json={"error": {"message": "bad key"}})

    with pytest.raises(CaptureError) as e:
        sarvam_with(handler).transcribe_segments([b"a"])
    assert e.value.code == "stt_failed"
