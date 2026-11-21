"""Make the question clean before it reaches search and the answer writer.

Two steps:
1. pre_clean()  (no AI, instant)
   - collapses spaces, drops filler sounds (umm, uh, hmm, matlab, achha…) and words repeated by accident
   - normalises error codes: "e 5", "E05", "ई 05" -> "E-05"
   - normalises this plant's machine codes: "hp 7", "HP07", "hp-07" -> "HP-07"
   - Indian-script digits -> 0-9 (so codes and values match the manuals)
2. understand()  (gpt-oss-20b, strict JSON)
   - one clean, complete English question for search and for the writer
   - self-corrections resolved ("pressure… no wait, oil is leaking" -> oil leak)
   - error codes, what the technician already tried, and whether it's a repair question at all
   If the call fails, the pre-cleaned text is used (never blocks an answer).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

log = logging.getLogger("kaarigar.assist.understand")

# Filler sounds only: never words that carry meaning ("nahi", "kam", "zyada" stay).
FILLERS = {
    "um", "umm", "ummm", "uh", "uhh", "uhm", "hmm", "hmmm", "erm", "er", "ah", "aah", "eh",
    "matlab", "achha", "acha", "accha", "haan", "han", "arey", "arre", "yaar",
    "अं", "उम्म", "हम्म", "मतलब", "अच्छा", "हाँ", "अरे", "यार",
}
_EN_DIGITS = str.maketrans("०१२३४५६७८९০১২৩৪৫৬৭৮৯੦੧੨੩੪੫੬੭੮੯૦૧૨૩૪૫૬૭૮૯୦୧୨୩୪୫୬୭୮୯௦௧௨௩௪௫௬௭௮௯౦౧౨౩౪౫౬౭౮౯೦೧೨೩೪೫೬೭೮೯൦൧൨൩൪൫൬൭൮൯",
                           "0123456789" * 9)
_ERROR_CODE = re.compile(r"(?<![A-Za-z0-9])(?:[eE]|ई)\s?-?\s?(\d{1,2})(?![0-9])")
_WORD = re.compile(r"\S+")


def _strip_punct(w: str) -> str:
    return w.strip(".,!?;:\"'()[]{}…।")


def pre_clean(text: str, machine_codes: list[str] | None = None) -> str:
    t = " ".join((text or "").split()).translate(_EN_DIGITS)
    # error codes: E 5 / e05 / ई 05 -> E-05
    t = _ERROR_CODE.sub(lambda m: f"E-{int(m.group(1)):02d}", t)
    # machine codes of this plant: tolerate spaces, missing dash and missing leading zero (hp7, HP 07, hp-07)
    for code in machine_codes or []:
        m = re.fullmatch(r"([A-Za-z]+)-?(\d+)", code.strip())
        if not m:
            continue
        letters, num = m.group(1), m.group(2)
        pat = re.compile(rf"(?<![A-Za-z0-9]){letters}\s?-?\s?0*{int(num)}(?![0-9])", re.IGNORECASE)
        t = pat.sub(code.upper(), t)
    # fillers and accidental repeats ("pump pump", "the the")
    out: list[str] = []
    for w in _WORD.findall(t):
        core = _strip_punct(w).lower()
        if core in FILLERS:
            continue
        if out and core and _strip_punct(out[-1]).lower() == core:
            continue
        out.append(w)
    cleaned = " ".join(out).strip(" ,")
    return cleaned or " ".join((text or "").split())


class Understanding(BaseModel):
    question_en: str
    error_codes: list[str] = Field(default_factory=list)
    already_tried: str | None = None
    is_repair_question: bool = True

    @field_validator("question_en")
    @classmethod
    def _clean_q(cls, v: str) -> str:
        return " ".join(v.split())[:500]

    @field_validator("already_tried")
    @classmethod
    def _blank(cls, v: str | None) -> str | None:
        v = " ".join((v or "").split())
        return v[:300] or None

    @field_validator("error_codes")
    @classmethod
    def _codes(cls, v: list[str]) -> list[str]:
        return [c.strip().upper() for c in v if c and c.strip()][:5]


UNDERSTAND_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["question_en", "error_codes", "already_tried", "is_repair_question"],
    "properties": {
        "question_en": {"type": "string"},
        "error_codes": {"type": "array", "items": {"type": "string"}},
        "already_tried": {"type": ["string", "null"]},
        "is_repair_question": {"type": "boolean"},
    },
}

UNDERSTAND_SYSTEM = """You prepare a factory technician's spoken question for a repair search engine.
The text was spoken on a noisy shop floor, in an Indian language or Hinglish, and machine-transcribed.

Return:
- question_en: ONE clear, complete English question about the problem, as the technician means it.
  Remove filler words and repetitions. If they corrected themselves, keep only the corrected version.
  Keep machine codes, error/alarm codes, part numbers, numbers and units exactly (HP-07, E-05, 210 bar).
  Keep sound words like thak-thak or khat-khat. Do NOT add causes, fixes or details they didn't say.
- error_codes: error or alarm codes mentioned (E-05, 2001), else [].
- already_tried: what they say they already did or checked, in short English, else null.
- is_repair_question: false ONLY if it is clearly not about machines, maintenance, safety or production
  (for example food, salary, phones, greetings). When unsure, true."""


def understand_user(text: str, machine: dict | None) -> str:
    m = machine["code"] if machine else "not selected"
    return f"Machine: {m}\nTechnician said:\n\"\"\"\n{text[:800]}\n\"\"\""


def understand(structured_llm: Any, model: str, text: str, machine: dict | None) -> Understanding | None:
    try:
        return structured_llm.structured(model=model, system=UNDERSTAND_SYSTEM, user=understand_user(text, machine),
                                         schema_name="understanding", schema=UNDERSTAND_SCHEMA, out=Understanding,
                                         max_tokens=400)
    except Exception as e:  # noqa: BLE001  (CaptureError from Phase 2's GroqLLM, validation, network)
        log.info("understand step failed: %s", type(e).__name__)
        return None


def needs_ai(text: str, language: str, voice: bool) -> bool:
    """Spoken questions always get the AI clean-up. Typed ones only if not plain short English."""
    if voice:
        return True
    from app.capture.languages import is_english

    return (not is_english(language)) or any(ord(ch) > 127 for ch in text) or len(text.split()) > 14
