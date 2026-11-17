"""Sarvam Saaras speech-to-text.

POST https://api.sarvam.ai/speech-to-text  (multipart)
  header  api-subscription-key
  fields  file, model=saaras:v3, mode=translate, language_code=unknown (auto-detect)
Response: {request_id, transcript, language_code, language_probability?}
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

from .errors import USER_MESSAGES, CaptureError

log = logging.getLogger("kaarigar.capture.sarvam")
BASE_URL = "https://api.sarvam.ai"


@dataclass
class SttResult:
    transcript: str
    language_code: str | None = None
    request_ids: list[str] = field(default_factory=list)


class SarvamClient:
    def __init__(self, api_key: str, *, model: str = "saaras:v3", mode: str = "translate",
                 timeout: float = 60.0, http: httpx.Client | None = None, max_retries: int = 2):
        if not api_key:
            raise RuntimeError("SARVAM_API_KEY is not set")
        self.model = model
        self.mode = mode
        self.max_retries = max_retries
        self._http = http or httpx.Client(base_url=BASE_URL, timeout=timeout,
                                          headers={"api-subscription-key": api_key})

    def _one(self, wav: bytes, language_code: str) -> dict:
        data = {"model": self.model, "mode": self.mode, "language_code": language_code}
        files = {"file": ("note.wav", wav, "audio/wav")}
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                r = self._http.post("/speech-to-text", data=data, files=files)
            except httpx.HTTPError as e:  # network / timeout
                last_exc = e
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503) and attempt < self.max_retries:
                wait = float(r.headers.get("retry-after", 2 * (attempt + 1)))
                time.sleep(min(wait, 15))
                continue
            # 400/403/422 or retries used up: log status only (never the key or audio)
            log.warning("sarvam stt failed status=%s", r.status_code)
            raise CaptureError("stt_failed", USER_MESSAGES["stt_failed"])
        log.warning("sarvam stt network error: %s", type(last_exc).__name__)
        raise CaptureError("stt_failed", USER_MESSAGES["stt_failed"])

    def transcribe_segments(self, segments: list[bytes], language_code: str | None = None) -> SttResult:
        """Transcribe (and translate to English) each segment in order and join the text."""
        parts: list[str] = []
        lang_votes: dict[str, float] = {}
        req_ids: list[str] = []
        for seg in segments:
            js = self._one(seg, language_code or "unknown")
            text = (js.get("transcript") or "").strip()
            if text:
                parts.append(text)
            lc = js.get("language_code")
            if lc:
                lang_votes[lc] = lang_votes.get(lc, 0) + len(text) + 1
            if js.get("request_id"):
                req_ids.append(js["request_id"])
        detected = max(lang_votes, key=lang_votes.get) if lang_votes else None
        return SttResult(transcript=" ".join(parts).strip(), language_code=detected, request_ids=req_ids)
