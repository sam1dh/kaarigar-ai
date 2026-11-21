"""Safe diagnostics for LLM calls.

Logs status codes, exception types and a rough prompt-size estimate. Never logs
prompts, questions, answers, transcripts or API keys.
"""
from __future__ import annotations


def estimate_tokens(*texts: str | None) -> int:
    """Rough prompt size: ~4 characters per token. Good enough to spot a 413/TPM issue."""
    return max(1, sum(len(t or "") for t in texts) // 4)


def status_code(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def describe(exc: Exception) -> str:
    """A one-line, content-free description for logs."""
    code = status_code(exc)
    return f"status={code if code is not None else 'n/a'} error={type(exc).__name__}"
