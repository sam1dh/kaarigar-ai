"""Sarvam Bulbul text-to-speech (read aloud fallback when the phone has no voice for the language).

POST https://api.sarvam.ai/text-to-speech   header api-subscription-key
JSON {text, target_language_code, speaker, model: "bulbul:v3"}  ->  {"audios": ["<base64 wav>"]}
bulbul:v3 takes up to 2500 characters in one request.
"""
from __future__ import annotations

import base64
import logging

import httpx

from .errors import AssistError

log = logging.getLogger("kaarigar.assist.tts")
BASE_URL = "https://api.sarvam.ai"


class SarvamTTS:
    def __init__(self, api_key: str, *, model: str = "bulbul:v3", speaker: str = "shubh", timeout: float = 45.0,
                 max_chars: int = 2500, http: httpx.Client | None = None):
        if not api_key:
            raise RuntimeError("SARVAM_API_KEY is not set")
        self.model = model
        self.speaker = speaker
        self.max_chars = max_chars
        self._http = http or httpx.Client(base_url=BASE_URL, timeout=timeout,
                                          headers={"api-subscription-key": api_key})

    def synthesize(self, text: str, language: str) -> bytes:
        text = text.strip()
        if not text:
            raise AssistError("tts_failed")
        if len(text) > self.max_chars:
            text = text[: self.max_chars].rsplit(" ", 1)[0]
        body = {"text": text, "target_language_code": language or "en-IN", "speaker": self.speaker,
                "model": self.model}
        try:
            r = self._http.post("/text-to-speech", json=body)
        except httpx.HTTPError as e:
            log.warning("sarvam tts network error: %s", type(e).__name__)
            raise AssistError("tts_failed") from e
        if r.status_code != 200:
            log.warning("sarvam tts failed status=%s", r.status_code)
            raise AssistError("tts_failed")
        audios = (r.json() or {}).get("audios") or []
        if not audios:
            raise AssistError("tts_failed")
        try:
            return base64.b64decode(audios[0])
        except Exception as e:  # noqa: BLE001
            raise AssistError("tts_failed") from e
