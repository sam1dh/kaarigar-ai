"""A small OpenAI-compatible HTTP client (no vendor SDKs).

Groq, Mistral, Gemini (OpenAI compatibility), OpenRouter, Whisper and Deepgram
all accept HTTP requests in the same shape. Keeping one tiny client means a new
provider is configuration, not new code. It never logs prompts, audio or keys.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator

import httpx

from .provider_config import LLMProvider

log = logging.getLogger("kaarigar.core.provider_http")


class ProviderError(Exception):
    """A provider call failed. Safe to log: no prompt/audio content is attached."""

    def __init__(self, provider: str, *, status: int | None = None, kind: str = "error",
                 retry_after: float | None = None):
        super().__init__(f"{provider}:{kind}:{status}")
        self.provider = provider
        self.status = status
        self.kind = kind
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        if self.kind in ("timeout", "network"):
            return True
        return self.status in (408, 413, 429) or (self.status is not None and 500 <= self.status < 600)


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _content_text(payload: Any) -> str:
    """OpenAI returns content as a string; a few gateways return a list of parts."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        return "".join(p.get("text", "") for p in payload if isinstance(p, dict))
    return ""


class OpenAICompatClient:
    def __init__(self, *, timeout: float = 8.0, http: httpx.Client | None = None):
        self.timeout = timeout
        self._http = http or httpx.Client(timeout=httpx.Timeout(timeout))

    # ------------------------------------------------------------------ chat
    def stream_chat(self, provider: LLMProvider, messages: list[dict], *, max_tokens: int,
                    temperature: float = 0.2, reasoning_effort: str | None = "low",
                    timeout: float | None = None) -> Iterator[str]:
        body: dict[str, Any] = {
            "model": provider.model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # gpt-oss models accept reasoning_effort on Groq/OpenRouter; other providers reject it.
        if reasoning_effort and provider.name in ("groq", "openrouter"):
            body["reasoning_effort"] = reasoning_effort
        headers = self._headers(provider)
        url = provider.base_url.rstrip("/") + "/chat/completions"
        t = timeout if timeout is not None else self.timeout
        try:
            with self._http.stream("POST", url, json=body, headers=headers,
                                   timeout=httpx.Timeout(t)) as resp:
                if resp.status_code != 200:
                    retry = _retry_after(resp)
                    resp.read()                       # drain, never logged
                    raise ProviderError(provider.name, status=resp.status_code, kind="http",
                                        retry_after=retry)
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data = line[5:].strip()
                    elif line.startswith("{"):
                        data = line.strip()                # a few gateways omit the SSE prefix
                    else:
                        continue
                    if data == "[DONE]":
                        return
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    text = _content_text(delta.get("content"))
                    if text:
                        yield text
        except httpx.TimeoutException as e:
            raise ProviderError(provider.name, kind="timeout") from e
        except httpx.HTTPError as e:
            raise ProviderError(provider.name, kind="network") from e

    def chat(self, provider: LLMProvider, messages: list[dict], *, max_tokens: int,
             temperature: float = 0.0, response_format: dict | None = None,
             reasoning_effort: str | None = "low", timeout: float | None = None) -> str:
        body: dict[str, Any] = {
            "model": provider.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            body["response_format"] = response_format
        if reasoning_effort and provider.name in ("groq", "openrouter"):
            body["reasoning_effort"] = reasoning_effort
        url = provider.base_url.rstrip("/") + "/chat/completions"
        t = timeout if timeout is not None else self.timeout
        try:
            resp = self._http.post(url, json=body, headers=self._headers(provider),
                                   timeout=httpx.Timeout(t))
        except httpx.TimeoutException as e:
            raise ProviderError(provider.name, kind="timeout") from e
        except httpx.HTTPError as e:
            raise ProviderError(provider.name, kind="network") from e
        if resp.status_code != 200:
            raise ProviderError(provider.name, status=resp.status_code, kind="http",
                                retry_after=_retry_after(resp))
        try:
            payload = resp.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise ProviderError(provider.name, kind="malformed") from e
        return _content_text(content)

    @staticmethod
    def _headers(provider: LLMProvider) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
        if provider.name == "openrouter":
            headers["HTTP-Referer"] = "https://app.kaarigar-ai.online"
            headers["X-Title"] = "Kaarigar AI"
        return headers
