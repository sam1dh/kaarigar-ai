"""Errors for the capture pipeline.

CaptureError carries a stable `code` and a `user_message` that is safe to show the technician.
API errors use the Phase 0 format: {"error": {"code", "message"}}.
"""
from fastapi import HTTPException


class CaptureError(Exception):
    """A pipeline step failed in a way the expert should hear about."""

    def __init__(self, code: str, user_message: str, *, retryable: bool = True):
        super().__init__(f"{code}: {user_message}")
        self.code = code
        self.user_message = user_message
        self.retryable = retryable


USER_MESSAGES = {
    "no_speech": "We couldn't hear a repair note. Record again a little closer to the phone.",
    "too_short": "The recording is too short. Hold the button and describe the repair.",
    "too_long": "The recording is too long. Keep it under 3 minutes.",
    "bad_audio": "This recording couldn't be read. Please record again.",
    "stt_failed": "Speech service is busy. Tap Try again in a minute.",
    "llm_failed": "The AI helper is busy. Tap Try again in a minute.",
    "server_restarted": "The server restarted while working on your note. Tap Try again.",
    "internal": "Something went wrong while working on your note. Tap Try again.",
}


def api_error(status: int, code: str, message: str) -> HTTPException:
    """Raise as `raise api_error(...)`.

    ADAPT (3.2): this repo's Phase 0 error class is app.core.errors.ApiError; its
    installed handler turns it into the standard {"error": {"code", "message"}}
    body. Raising it directly guarantees the Phase 0 shape on every response.
    """
    from app.core.errors import ApiError

    return ApiError(status, code, message)
