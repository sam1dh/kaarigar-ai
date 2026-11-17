"""Language helpers. Codes are Sarvam's (same as shared/languages.json)."""

NAMES = {
    "en-IN": "English",
    "hi-IN": "Hindi",
    "pa-IN": "Punjabi",
    "mr-IN": "Marathi",
    "gu-IN": "Gujarati",
    "bn-IN": "Bengali",
    "od-IN": "Odia",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
    "kn-IN": "Kannada",
    "ml-IN": "Malayalam",
}


def is_english(code: str | None) -> bool:
    return not code or code.lower().startswith("en")


def language_name(code: str | None) -> str:
    if not code:
        return "English"
    return NAMES.get(code, code)
