"""Speech-to-text fallback chain.

Order: Sarvam saaras:v3 -> Groq whisper-large-v3 -> Azure Speech F0 REST ->
Deepgram (only when its key is configured). Each segment is tried on the first
provider; if that provider fails, the same audio goes to the next one. Logs have
provider, status and latency only — never audio or transcript content.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Iterable

import httpx

from .breaker import CircuitBreaker
from .provider_config import STTProvider

log = logging.getLogger("kaarigar.core.stt_chain")


class STTUnavailable(Exception):
    """Every STT provider failed. Callers map this to their friendly error."""


class STTChain:
    def __init__(self, providers: list[STTProvider], *, breaker: CircuitBreaker | None = None,
                 timeout: float = 60.0, http: httpx.Client | None = None,
                 error_factory: Callable[[], Exception] | None = None):
        self.providers = providers
        self.breaker = breaker or CircuitBreaker()
        self.timeout = timeout
        self._http = http or httpx.Client(timeout=httpx.Timeout(timeout))
        self.error_factory = error_factory or (lambda: STTUnavailable("no stt provider"))

    def transcribe_segments(self, segments: Iterable[bytes], language_code: str | None = None) -> Any:
        from app.capture.sarvam import SttResult           # same shape Phase 2 already uses

        parts: list[str] = []
        votes: dict[str, float] = {}
        req_ids: list[str] = []
        for seg in segments:
            text, lc, rid = self._one(seg, language_code or "unknown")
            if text:
                parts.append(text.strip())
            if lc:
                votes[lc] = votes.get(lc, 0) + len(text) + 1
            if rid:
                req_ids.append(rid)
        detected = max(votes, key=votes.get) if votes else None
        return SttResult(transcript=" ".join(parts).strip(), language_code=detected, request_ids=req_ids)

    # ------------------------------------------------------------------ one segment
    def _one(self, wav: bytes, language: str) -> tuple[str, str | None, str | None]:
        last: Exception | None = None
        for p in self.providers:
            if not self.breaker.allow(p.name):
                continue
            started = time.monotonic()
            try:
                text, lc, rid = self._call(p, wav, language)
                self.breaker.success(p.name)
                log.info("stt provider=%s ok latency_ms=%d", p.name,
                         int((time.monotonic() - started) * 1000))
                return text, lc, rid
            except Exception as e:  # noqa: BLE001
                last = e
                self.breaker.failure(p.name)
                status = getattr(e, "status", None) or getattr(getattr(e, "response", None), "status_code", None)
                log.info("stt provider=%s failed status=%s kind=%s latency_ms=%d", p.name,
                         status or "n/a", type(e).__name__, int((time.monotonic() - started) * 1000))
                continue
        raise self.error_factory() from last

    def _call(self, p: STTProvider, wav: bytes, language: str) -> tuple[str, str | None, str | None]:
        if p.kind == "sarvam":
            return self._sarvam(p, wav, language)
        if p.kind == "groq":
            return self._groq(p, wav, language)
        if p.kind == "azure":
            return self._azure(p, wav, language)
        if p.kind == "deepgram":
            return self._deepgram(p, wav, language)
        raise STTUnavailable(f"unknown stt provider {p.name}")

    def _sarvam(self, p: STTProvider, wav: bytes, language: str) -> tuple[str, str | None, str | None]:
        r = self._http.post(
            p.base_url.rstrip("/") + "/speech-to-text",
            data={"model": p.model, "mode": p.mode, "language_code": language},
            files={"file": ("note.wav", wav, "audio/wav")},
            headers={"api-subscription-key": p.api_key},
            timeout=httpx.Timeout(self.timeout),
        )
        if r.status_code != 200:
            raise _HTTPStatus(r.status_code)
        js = r.json() or {}
        return (js.get("transcript") or "").strip(), js.get("language_code"), js.get("request_id")

    def _groq(self, p: STTProvider, wav: bytes, language: str) -> tuple[str, str | None, str | None]:
        data = {"model": p.model, "response_format": "json", "temperature": "0"}
        if language and language != "unknown":
            data["language"] = language.split("-")[0]
        r = self._http.post(
            p.base_url.rstrip("/") + "/audio/transcriptions",
            data=data, files={"file": ("note.wav", wav, "audio/wav")},
            headers={"Authorization": f"Bearer {p.api_key}"},
            timeout=httpx.Timeout(self.timeout),
        )
        if r.status_code != 200:
            raise _HTTPStatus(r.status_code)
        return ((r.json() or {}).get("text") or "").strip(), None, None

    def _azure(self, p: STTProvider, wav: bytes, language: str) -> tuple[str, str | None, str | None]:
        lang = language if language and language != "unknown" else "en-IN"
        r = self._http.post(
            p.base_url,
            params={"language": lang},
            content=wav,
            headers={"Ocp-Apim-Subscription-Key": p.api_key,
                     "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                     "Accept": "application/json"},
            timeout=httpx.Timeout(self.timeout),
        )
        if r.status_code != 200:
            raise _HTTPStatus(r.status_code)
        js = r.json() or {}
        if (js.get("RecognitionStatus") or "").lower() not in ("success", ""):
            raise STTUnavailable("azure recognition status")
        return (js.get("DisplayText") or "").strip(), lang if js.get("DisplayText") else None, None

    def _deepgram(self, p: STTProvider, wav: bytes, language: str) -> tuple[str, str | None, str | None]:
        params = {"model": p.model, "smart_format": "true", "punctuate": "true"}
        if language and language != "unknown":
            params["language"] = language
        r = self._http.post(
            p.base_url.rstrip("/") + "/listen", params=params, content=wav,
            headers={"Authorization": f"Token {p.api_key}", "Content-Type": "audio/wav"},
            timeout=httpx.Timeout(self.timeout),
        )
        if r.status_code != 200:
            raise _HTTPStatus(r.status_code)
        try:
            js = r.json() or {}
            alt = js["results"]["channels"][0]["alternatives"][0]
        except (KeyError, IndexError, TypeError) as e:
            raise STTUnavailable("deepgram shape") from e
        lc = (js.get("results", {}).get("channels", [{}])[0].get("detected_language")) or None
        return (alt.get("transcript") or "").strip(), lc, None


class _HTTPStatus(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status
