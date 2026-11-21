"""Text-to-speech fallback chain: Sarvam Bulbul -> Azure neural voice -> browser.

The browser is the final fallback, chosen by the API route when this chain has
no provider or every provider fails. Nothing is logged except provider, status
and latency.
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Callable
from xml.sax.saxutils import escape

import httpx

from .breaker import CircuitBreaker
from .provider_config import AZURE_SPEECH_TTS, AZURE_VOICES, TTSProvider

log = logging.getLogger("kaarigar.core.tts_chain")

AZURE_OUTPUT = "riff-24khz-16bit-mono-pcm"


class TTSUnavailable(Exception):
    """No server-side voice worked. The route asks the phone to speak instead."""


class TTSChain:
    def __init__(self, providers: list[TTSProvider], *, breaker: CircuitBreaker | None = None,
                 timeout: float = 45.0, max_chars: int = 2500, http: httpx.Client | None = None,
                 error_factory: Callable[[], Exception] | None = None):
        self.providers = providers
        self.breaker = breaker or CircuitBreaker()
        self.timeout = timeout
        self.max_chars = max_chars
        self._http = http or httpx.Client(timeout=httpx.Timeout(timeout))
        self.error_factory = error_factory or (lambda: TTSUnavailable("no tts provider"))

    def synthesize(self, text: str, language: str) -> bytes:
        text = " ".join((text or "").split())
        if not text:
            raise self.error_factory()
        if len(text) > self.max_chars:
            text = text[: self.max_chars].rsplit(" ", 1)[0]
        lang = language or "en-IN"
        last: Exception | None = None
        for p in self.providers:
            if not self.breaker.allow(p.name):
                continue
            started = time.monotonic()
            try:
                wav = self._sarvam(p, text, lang) if p.kind == "sarvam" else self._azure(p, text, lang)
                self.breaker.success(p.name)
                log.info("tts provider=%s ok latency_ms=%d", p.name,
                         int((time.monotonic() - started) * 1000))
                return wav
            except Exception as e:  # noqa: BLE001
                last = e
                self.breaker.failure(p.name)
                status = getattr(e, "status", None) or getattr(getattr(e, "response", None), "status_code", None)
                log.info("tts provider=%s failed status=%s kind=%s latency_ms=%d", p.name,
                         status or "n/a", type(e).__name__, int((time.monotonic() - started) * 1000))
                continue
        raise self.error_factory() from last

    def _sarvam(self, p: TTSProvider, text: str, lang: str) -> bytes:
        r = self._http.post(
            "https://api.sarvam.ai/text-to-speech",
            json={"text": text, "target_language_code": lang, "speaker": p.speaker, "model": p.model},
            headers={"api-subscription-key": p.api_key},
            timeout=httpx.Timeout(self.timeout),
        )
        if r.status_code != 200:
            raise _HTTPStatus(r.status_code)
        audios = (r.json() or {}).get("audios") or []
        if not audios:
            raise TTSUnavailable("sarvam empty audio")
        return base64.b64decode(audios[0])

    def _azure(self, p: TTSProvider, text: str, lang: str) -> bytes:
        voice = AZURE_VOICES.get(lang) or AZURE_VOICES.get(lang.split("-")[0] + "-IN") or AZURE_VOICES["en-IN"]
        ssml_lang = lang if lang in AZURE_VOICES else ("or-IN" if lang == "od-IN" else "en-IN")
        ssml = (f"<speak version='1.0' xml:lang='{ssml_lang}'>"
                f"<voice xml:lang='{ssml_lang}' name='{voice}'>{escape(text)}</voice></speak>")
        r = self._http.post(
            AZURE_SPEECH_TTS.format(region=p.region),
            content=ssml.encode("utf-8"),
            headers={"Ocp-Apim-Subscription-Key": p.api_key,
                     "Content-Type": "application/ssml+xml",
                     "X-Microsoft-OutputFormat": AZURE_OUTPUT},
            timeout=httpx.Timeout(self.timeout),
        )
        if r.status_code != 200:
            raise _HTTPStatus(r.status_code)
        if not r.content:
            raise TTSUnavailable("azure empty audio")
        return r.content


class _HTTPStatus(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status
