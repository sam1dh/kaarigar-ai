"""Groq calls for Assist.

- GroqWriter.stream(): the answer, token by token. If the first model is rate-limited or down *before*
  any text arrives, the next model is tried (120b -> 20b). A failure after text started is an error.
- GroqWriter.text(): one plain-text reply (answer -> English for managers). Returns None on failure.
- question_to_english(): structured call through Phase 2's GroqLLM (strict JSON, validated).
Never logs prompts, questions, answers or keys.
"""
from __future__ import annotations

import logging
from typing import Any, Iterator

from pydantic import BaseModel

from .errors import AssistError
from .prompts import QUESTION_EN_SCHEMA, QUESTION_EN_SYSTEM

log = logging.getLogger("kaarigar.assist.llm")


class QuestionEn(BaseModel):
    question_en: str


class GroqWriter:
    def __init__(self, api_key: str, *, timeout: float = 45.0, client: Any = None):
        if client is not None:
            self.client = client
        else:
            if not api_key:
                raise RuntimeError("GROQ_API_KEY is not set")
            from groq import Groq

            self.client = Groq(api_key=api_key, timeout=timeout, max_retries=0)
        self.model_used: str | None = None

    def stream(self, *, models: list[str], system: str, user: str, max_tokens: int = 900) -> Iterator[str]:
        import groq

        retry_before_text = (groq.RateLimitError, groq.APIConnectionError, groq.APITimeoutError,
                             groq.InternalServerError)
        last: Exception | None = None
        for model in [m for m in models if m]:
            try:
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    stream=True,
                    temperature=0.2,
                    max_completion_tokens=max_tokens,
                    reasoning_effort="low",
                )
            except retry_before_text as e:
                log.info("groq %s unavailable before streaming (%s), trying next model", model, type(e).__name__)
                last = e
                continue
            except groq.APIError as e:   # 400/401/403/404: retrying another model won't help
                log.warning("groq %s refused the request: %s", model, type(e).__name__)
                raise AssistError("llm_failed") from e

            self.model_used = model
            started = False
            try:
                for chunk in resp:
                    choices = getattr(chunk, "choices", None) or []
                    if not choices:
                        continue
                    text = getattr(choices[0].delta, "content", None)
                    if text:
                        started = True
                        yield text
                return
            except Exception as e:  # noqa: BLE001  stream broke
                if started:
                    log.warning("groq stream broke after text started: %s", type(e).__name__)
                    raise AssistError("llm_failed") from e
                last = e
                continue
            finally:
                close = getattr(resp, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:  # noqa: BLE001
                        pass
        raise AssistError("llm_failed") from last

    def text(self, *, model: str, system: str, user: str, max_tokens: int = 900) -> str | None:
        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0,
                max_completion_tokens=max_tokens,
                reasoning_effort="low",
            )
            return (resp.choices[0].message.content or "").strip() or None
        except Exception as e:  # noqa: BLE001
            log.info("groq text call failed: %s", type(e).__name__)
            return None


def question_to_english(structured_llm: Any, model: str, text: str) -> str | None:
    """Spoken/typed question in any language -> English. None if the call fails (caller falls back)."""
    try:
        out = structured_llm.structured(model=model, system=QUESTION_EN_SYSTEM, user=text[:600],
                                        schema_name="question", schema=QUESTION_EN_SCHEMA, out=QuestionEn,
                                        max_tokens=300)
        q = " ".join(out.question_en.split())
        return q or None
    except Exception as e:  # noqa: BLE001  (CaptureError from Phase 2's GroqLLM, or anything else)
        log.info("question translation failed: %s", type(e).__name__)
        return None
