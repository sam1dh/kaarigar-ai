"""LLM fallback chains: one writer for answers, one structured caller for JSON.

Order is set by :mod:`app.core.provider_config`. A candidate is skipped when the
breaker is open or ``DISABLE_PROVIDERS`` names its provider. Failures before the
first token fall through to the next candidate; a breaker failure after the user
has already seen text stops (we never mix two answers).

Citation fallback: the writer can hold an answer until a valid-looking reference
appears. If an answer finishes with no valid citations, it is discarded and the
next provider writes it instead, so the technician never sees an uncited answer.

Logs contain provider, model, status code, error kind and latency only.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Iterator, TypeVar

from pydantic import BaseModel, ValidationError

from .breaker import CircuitBreaker
from .llm_diagnostics import describe, estimate_tokens
from .openai_compat import OpenAICompatClient, ProviderError
from .provider_config import LLMProvider

log = logging.getLogger("kaarigar.core.llm_chain")
T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class LLMUnavailable(Exception):
    """No provider could answer. Callers map this to their own friendly error."""


def _messages(system: str, user: str) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def json_text(text: str) -> str:
    """Some providers wrap JSON in a markdown fence even in JSON mode."""
    return _FENCE.sub("", (text or "").strip())


def _with_model_first(providers: list[LLMProvider], model: str | None) -> list[LLMProvider]:
    if not model:
        return providers
    first = [p for p in providers if p.model == model]
    rest = [p for p in providers if p.model != model]
    return first + rest


class LLMChainWriter:
    """GroqWriter-compatible chain used by Assist's answer writer."""

    accepts_validation = True

    def __init__(self, providers: list[LLMProvider], *, breaker: CircuitBreaker | None = None,
                 client: OpenAICompatClient | None = None, timeout: float = 8.0,
                 error_factory: Callable[[], Exception] | None = None):
        self.providers = providers
        self.breaker = breaker or CircuitBreaker()
        self.client = client or OpenAICompatClient(timeout=timeout)
        self.timeout = timeout
        self.error_factory = error_factory or (lambda: LLMUnavailable("no provider"))
        self.model_used: str | None = None
        self.provider_used: str | None = None
        self.last_error: Exception | None = None

    # ------------------------------------------------------------------ stream
    def stream(self, *, models: list[str] | None = None, system: str, user: str,
               max_tokens: int = 700, temperature: float = 0.2,
               validate: Callable[[str], bool] | None = None,
               flush_when: Callable[[str], bool] | None = None) -> Iterator[str]:
        prompt_tokens = estimate_tokens(system, user)
        candidates = [p for p in self.providers if self.breaker.allow(p.name)]
        if not candidates:
            log.warning("llm chain empty or all providers disabled prompt_tokens~%d", prompt_tokens)
            raise self.error_factory()

        for idx, cand in enumerate(candidates):
            started = time.monotonic()
            self.model_used = f"{cand.name}:{cand.model}"
            self.provider_used = cand.name
            released = False
            held: list[str] = []
            full: list[str] = []
            try:
                for chunk in self.client.stream_chat(cand, _messages(system, user), max_tokens=max_tokens,
                                                     temperature=temperature, timeout=self.timeout):
                    full.append(chunk)
                    if validate is None or released:
                        yield chunk
                        continue
                    held.append(chunk)
                    if flush_when and flush_when("".join(held)):
                        released = True
                        yield "".join(held)
                        held = []
                text = "".join(full)
                if validate is not None and not validate(text):
                    log.info("provider=%s model=%s invalid citations latency_ms=%d prompt_tokens~%d",
                             cand.name, cand.model, int((time.monotonic() - started) * 1000), prompt_tokens)
                    if idx + 1 < len(candidates) and not released:
                        continue                       # nothing shown yet: try the next provider
                    if not released and held:
                        yield "".join(held)             # last provider: best effort, caller marks no_answer
                    self.breaker.success(cand.name)
                    return
                if not released and held:
                    yield "".join(held)
                self.breaker.success(cand.name)
                log.info("provider=%s model=%s streamed latency_ms=%d prompt_tokens~%d",
                         cand.name, cand.model, int((time.monotonic() - started) * 1000), prompt_tokens)
                return
            except ProviderError as e:
                self.last_error = e
                if e.retryable:
                    self.breaker.failure(cand.name)
                log.info("provider=%s model=%s failed status=%s kind=%s latency_ms=%d prompt_tokens~%d",
                         cand.name, cand.model, e.status, e.kind,
                         int((time.monotonic() - started) * 1000), prompt_tokens)
                if released:
                    raise self.error_factory() from e    # text already sent: cannot switch safely
                if e.retry_after:
                    time.sleep(min(e.retry_after, 1.0))
                continue
            except Exception as e:  # noqa: BLE001  network/library errors
                self.last_error = e
                self.breaker.failure(cand.name)
                log.info("provider=%s model=%s failed %s latency_ms=%d prompt_tokens~%d",
                         cand.name, cand.model, describe(e),
                         int((time.monotonic() - started) * 1000), prompt_tokens)
                if released:
                    raise self.error_factory() from e
                continue
        raise self.error_factory()

    # ------------------------------------------------------------------ plain text
    def text(self, *, model: str | None = None, system: str, user: str, max_tokens: int = 600) -> str | None:
        prompt_tokens = estimate_tokens(system, user)
        for cand in _with_model_first(self.providers, model):
            if not self.breaker.allow(cand.name):
                continue
            started = time.monotonic()
            try:
                out = self.client.chat(cand, _messages(system, user), max_tokens=max_tokens,
                                       temperature=0, timeout=self.timeout)
                self.breaker.success(cand.name)
                self.model_used, self.provider_used = f"{cand.name}:{cand.model}", cand.name
                log.info("provider=%s model=%s text latency_ms=%d prompt_tokens~%d", cand.name, cand.model,
                         int((time.monotonic() - started) * 1000), prompt_tokens)
                return out.strip() or None
            except ProviderError as e:
                if e.retryable:
                    self.breaker.failure(cand.name)
                log.info("provider=%s model=%s text failed status=%s kind=%s latency_ms=%d prompt_tokens~%d",
                         cand.name, cand.model, e.status, e.kind,
                         int((time.monotonic() - started) * 1000), prompt_tokens)
                continue
            except Exception as e:  # noqa: BLE001
                self.breaker.failure(cand.name)
                log.info("provider=%s model=%s text failed %s prompt_tokens~%d",
                         cand.name, cand.model, describe(e), prompt_tokens)
                continue
        return None


class ChainStructured:
    """GroqLLM-compatible ``structured()`` across the same provider chain."""

    def __init__(self, providers: list[LLMProvider], *, breaker: CircuitBreaker | None = None,
                 client: OpenAICompatClient | None = None, timeout: float = 8.0,
                 error_factory: Callable[[], Exception] | None = None):
        self.providers = providers
        self.breaker = breaker or CircuitBreaker()
        self.client = client or OpenAICompatClient(timeout=timeout)
        self.timeout = timeout
        self.error_factory = error_factory or (lambda: LLMUnavailable("no provider"))
        self.model_used: str | None = None
        self.provider_used: str | None = None

    def structured(self, *, model: str | None = None, system: str, user: str, schema_name: str,
                   schema: dict, out: type[T], max_tokens: int = 1500,
                   reasoning_effort: str = "low") -> T:
        prompt_tokens = estimate_tokens(system, user)
        for cand in _with_model_first(self.providers, model):
            if not self.breaker.allow(cand.name):
                continue
            formats = self._formats(cand, schema_name, schema)
            for fmt in formats:
                started = time.monotonic()
                try:
                    content = self.client.chat(
                        cand, _messages(system, user), max_tokens=max_tokens, temperature=0,
                        response_format=fmt, reasoning_effort=reasoning_effort, timeout=self.timeout,
                    )
                    parsed = out.model_validate_json(json_text(content))
                    self.breaker.success(cand.name)
                    self.model_used, self.provider_used = f"{cand.name}:{cand.model}", cand.name
                    log.info("provider=%s model=%s json ok latency_ms=%d prompt_tokens~%d",
                             cand.name, cand.model, int((time.monotonic() - started) * 1000), prompt_tokens)
                    return parsed
                except ProviderError as e:
                    if e.status in (400, 422) and fmt is not formats[-1]:
                        log.info("provider=%s model=%s json format unsupported status=%s, trying simpler mode",
                                 cand.name, cand.model, e.status)
                        continue
                    if e.retryable:
                        self.breaker.failure(cand.name)
                    log.info("provider=%s model=%s json failed status=%s kind=%s latency_ms=%d prompt_tokens~%d",
                             cand.name, cand.model, e.status, e.kind,
                             int((time.monotonic() - started) * 1000), prompt_tokens)
                    break
                except ValidationError as e:
                    log.info("provider=%s model=%s json invalid latency_ms=%d prompt_tokens~%d",
                             cand.name, cand.model, int((time.monotonic() - started) * 1000), prompt_tokens)
                    break
                except Exception as e:  # noqa: BLE001
                    self.breaker.failure(cand.name)
                    log.info("provider=%s model=%s json failed %s prompt_tokens~%d",
                             cand.name, cand.model, describe(e), prompt_tokens)
                    break
        raise self.error_factory()

    @staticmethod
    def _formats(cand: LLMProvider, schema_name: str, schema: dict) -> list[dict | None]:
        if cand.supports_schema:
            return [
                {"type": "json_schema",
                 "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
                {"type": "json_object"},
                None,
            ]
        # Mistral and Gemini's OpenAI-compatible endpoint favour plain JSON mode.
        return [{"type": "json_object"}, None]
