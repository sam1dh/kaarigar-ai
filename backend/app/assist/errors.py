"""Errors for Assist. `code` is stable (the app translates it); `user_message` is the English fallback."""
from app.capture.errors import api_error  # noqa: F401  same {"error": {code, message}} shape as Phase 2


class AssistError(Exception):
    def __init__(self, code: str, user_message: str | None = None):
        super().__init__(code)
        self.code = code
        self.user_message = user_message or USER_MESSAGES.get(code, USER_MESSAGES["internal"])


USER_MESSAGES = {
    "no_speech": "We couldn't hear a question. Hold the phone closer and ask again.",
    "too_short": "That was too short. Tap the button and ask your question.",
    "too_long": "Keep your question under one minute.",
    "bad_audio": "This recording couldn't be read. Please ask again.",
    "stt_failed": "The speech service is busy. Try again in a minute, or type your question.",
    "llm_failed": "The AI helper is busy. Try again in a minute, or ask an expert.",
    "search_failed": "Kaarigar couldn't search its knowledge right now. Try again or ask an expert.",
    "busy": "Many people are asking right now. Try again in a minute.",
    "tts_failed": "Reading aloud isn't available right now.",
    "server_restarted": "The server restarted while answering. Ask again.",
    "internal": "Something went wrong while answering. Try again or ask an expert.",
}
