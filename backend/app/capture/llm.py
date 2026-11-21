"""Groq structured outputs, defensive.

1st try: strict json_schema (constrained decoding).
If Groq returns 400 (e.g. json_validate_failed) -> 2nd try with strict=false.
Every reply is validated with Pydantic. One wait on 429 (respects retry-after, capped).
Never logs prompts, transcripts or keys.
"""
from __future__ import annotations

import logging
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.llm_diagnostics import describe, estimate_tokens

from .errors import USER_MESSAGES, CaptureError

log = logging.getLogger("kaarigar.capture.llm")
T = TypeVar("T", bound=BaseModel)


class GroqLLM:
    def __init__(self, api_key: str, *, timeout: float = 45.0, client: Any = None):
        if client is not None:
            self.client = client
        else:
            if not api_key:
                raise RuntimeError("GROQ_API_KEY is not set")
            from groq import Groq

            self.client = Groq(api_key=api_key, timeout=timeout, max_retries=0)

    def structured(self, *, model: str, system: str, user: str, schema_name: str, schema: dict,
                   out: type[T], max_tokens: int = 1500, reasoning_effort: str = "low") -> T:
        import groq  # imported here so tests can run with a fake client

        prompt_tokens = estimate_tokens(system, user)
        attempts = [True, False]  # strict, then best-effort
        waited = False
        i = 0
        while i < len(attempts):
            strict = attempts[i]
            try:
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    response_format={"type": "json_schema",
                                     "json_schema": {"name": schema_name, "strict": strict, "schema": schema}},
                    temperature=0,
                    reasoning_effort=reasoning_effort,
                    max_completion_tokens=max_tokens,
                )
                content = resp.choices[0].message.content or ""
                return out.model_validate_json(content)
            except groq.RateLimitError as e:
                if waited:
                    log.warning("groq rate limited twice model=%s %s prompt_tokens~%d",
                                model, describe(e), prompt_tokens)
                    raise CaptureError("llm_failed", USER_MESSAGES["llm_failed"]) from e
                waited = True
                retry_after = 5.0
                try:
                    retry_after = float(e.response.headers.get("retry-after", 5))
                except Exception:  # noqa: BLE001
                    pass
                log.info("groq rate limited model=%s %s prompt_tokens~%d, waiting %.0fs",
                         model, describe(e), prompt_tokens, min(retry_after, 20))
                time.sleep(min(retry_after, 20))
                continue  # same attempt again
            except groq.BadRequestError as e:
                log.info("groq 400 with strict=%s model=%s %s prompt_tokens~%d, trying next mode",
                         strict, model, describe(e), prompt_tokens)
            except (groq.AuthenticationError, groq.PermissionDeniedError, groq.NotFoundError) as e:
                # A wrong/revoked key or a removed model is a configuration problem, not a
                # transcript problem. Surface it as the friendly "AI helper is busy" error
                # (ROB-03) instead of letting it bubble up as a generic `internal` failure.
                log.warning("groq rejected request model=%s %s prompt_tokens~%d",
                            model, describe(e), prompt_tokens)
                raise CaptureError("llm_failed", USER_MESSAGES["llm_failed"]) from e
            except ValidationError as e:
                log.info("groq reply failed validation strict=%s model=%s %s prompt_tokens~%d",
                         strict, model, describe(e), prompt_tokens)
            except (groq.APIConnectionError, groq.APITimeoutError, groq.InternalServerError) as e:
                log.warning("groq unavailable model=%s %s prompt_tokens~%d",
                            model, describe(e), prompt_tokens)
                raise CaptureError("llm_failed", USER_MESSAGES["llm_failed"]) from e
            i += 1
        raise CaptureError("llm_failed", USER_MESSAGES["llm_failed"])
