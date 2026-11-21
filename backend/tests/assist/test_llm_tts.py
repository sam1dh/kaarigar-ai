"""GroqWriter streaming + fallback, question translation, and Sarvam TTS — no network."""
import base64
import json
from types import SimpleNamespace

import groq
import httpx
import pytest

from app.assist.errors import AssistError
from app.assist.llm import GroqWriter, question_to_english
from app.assist.tts import SarvamTTS

from .fakes import FakeStructured


def _http_err(cls, status):
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return cls("x", response=httpx.Response(status, request=req, headers={"retry-after": "0"}), body=None)


def _chunk(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


class Stream:
    def __init__(self, parts, break_after=None):
        self.parts = parts
        self.break_after = break_after
        self.closed = False

    def __iter__(self):
        for i, p in enumerate(self.parts):
            if self.break_after is not None and i >= self.break_after:
                raise httpx.ReadError("connection reset")
            yield _chunk(p)
        yield SimpleNamespace(choices=[])           # usage chunk at the end has no choices

    def close(self):
        self.closed = True


class Completions:
    def __init__(self, script):
        self.script = list(script)
        self.kwargs = []

    def create(self, **kw):
        self.kwargs.append(kw)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def writer_with(script):
    comp = Completions(script)
    return GroqWriter("", client=SimpleNamespace(chat=SimpleNamespace(completions=comp))), comp


def run(w):
    return "".join(w.stream(models=["big", "small"], system="s", user="u", max_tokens=50))


def test_streams_and_closes():
    s = Stream(["1. Set ", "210 bar [E1]"])
    w, comp = writer_with([s])
    assert run(w) == "1. Set 210 bar [E1]"
    assert w.model_used == "big" and s.closed
    kw = comp.kwargs[0]
    assert kw["stream"] is True and kw["model"] == "big" and kw["reasoning_effort"] == "low"


def test_rate_limited_first_model_falls_back_before_text():
    w, comp = writer_with([_http_err(groq.RateLimitError, 429), Stream(["ok [E1]"])])
    assert run(w) == "ok [E1]"
    assert w.model_used == "small" and [k["model"] for k in comp.kwargs] == ["big", "small"]


def test_stream_breaking_before_text_falls_back():
    w, _ = writer_with([Stream(["x"], break_after=0), Stream(["fine"])])
    assert run(w) == "fine" and w.model_used == "small"


def test_stream_breaking_after_text_is_an_error():
    w, _ = writer_with([Stream(["a", "b", "c"], break_after=2), Stream(["never"])])
    with pytest.raises(AssistError) as e:
        run(w)
    assert e.value.code == "llm_failed"


def test_bad_request_does_not_try_other_models():
    w, comp = writer_with([_http_err(groq.BadRequestError, 400), Stream(["never"])])
    with pytest.raises(AssistError):
        run(w)
    assert len(comp.kwargs) == 1


def test_all_models_down():
    w, _ = writer_with([_http_err(groq.InternalServerError, 503), _http_err(groq.RateLimitError, 429)])
    with pytest.raises(AssistError) as e:
        run(w)
    assert e.value.code == "llm_failed"


def test_text_call_and_failure():
    ok = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=" Hello "))])
    w, _ = writer_with([ok, _http_err(groq.RateLimitError, 429)])
    assert w.text(model="m", system="s", user="u") == "Hello"
    assert w.text(model="m", system="s", user="u") is None


def test_question_to_english():
    assert question_to_english(FakeStructured(), "m", "प्रेशर") == "pressure is not building on HP-07"
    assert question_to_english(FakeStructured(fail_question=True), "m", "प्रेशर") is None


# ---------------------------------------------------------------------------- Sarvam TTS

def tts_with(handler):
    http = httpx.Client(base_url="https://api.sarvam.ai", transport=httpx.MockTransport(handler))
    return SarvamTTS("key", http=http, max_chars=40)


def test_tts_request_and_decode():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"request_id": "r", "audios": [base64.b64encode(b"RIFFdata").decode()]})

    wav = tts_with(handler).synthesize("1. Fit the gauge on the pump outlet and set 210 bar", "hi-IN")
    assert wav == b"RIFFdata"
    assert seen["path"] == "/text-to-speech"
    body = seen["body"]
    assert body["model"] == "bulbul:v3" and body["target_language_code"] == "hi-IN" and body["speaker"] == "shubh"
    assert len(body["text"]) <= 40 and not body["text"].endswith(" ")      # cut at a word boundary


@pytest.mark.parametrize("status", [400, 403, 429, 500])
def test_tts_errors(status):
    with pytest.raises(AssistError) as e:
        tts_with(lambda r: httpx.Response(status, json={})).synthesize("hello", "en-IN")
    assert e.value.code == "tts_failed"


def test_tts_empty_audio_and_empty_text():
    with pytest.raises(AssistError):
        tts_with(lambda r: httpx.Response(200, json={"audios": []})).synthesize("hello", "en-IN")
    with pytest.raises(AssistError):
        tts_with(lambda r: httpx.Response(200, json={"audios": ["x"]})).synthesize("   ", "en-IN")
