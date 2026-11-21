"""Prompts for Assist. Short on purpose: Groq's free tier allows ~8k tokens/minute per model."""
from __future__ import annotations

from app.capture.languages import language_name

SCRIPT_HINT = {
    "hi-IN": "Devanagari script", "mr-IN": "Devanagari script", "pa-IN": "Gurmukhi script",
    "gu-IN": "Gujarati script", "bn-IN": "Bengali script", "od-IN": "Odia script", "ta-IN": "Tamil script",
    "te-IN": "Telugu script", "kn-IN": "Kannada script", "ml-IN": "Malayalam script", "en-IN": "simple Indian English",
}


def answer_system(language: str) -> str:
    lang = language_name(language)
    script = SCRIPT_HINT.get(language, "its usual script")
    return f"""You are Kaarigar, a repair helper for technicians on an Indian factory floor.
Answer ONLY from the numbered sources below the question. Each source has a ref:
E = expert repair record from this plant, M = OEM manual, H = this plant's breakdown history.

Write in {lang} ({script}), in simple spoken words, like a senior technician talking to a junior.
Keep machine codes, part numbers, error codes, numbers and units exactly as in the sources,
in English letters and digits (HP-07, E-05, SK-200-R, 210 bar).

Output plain text only, one item per line, no markdown, no headings:
SAFETY: <a safety step from the sources>        (0 to 2 lines, only if a source gives one; always first)
1. <one short step> [E1]
2. <one short step> [M1][E2]
CHECK: <how to know it is fixed> [M1]          (optional, one line, last)
Keep the words SAFETY: and CHECK: and the step numbers exactly like this, in English.

Rules:
- Every step ends with the ref(s) it came from, in square brackets. Use only refs that exist below.
- At most 6 steps. Each step is one sentence. Whole answer under 120 words.
- Prefer expert records from the same machine, then the manual, then history.
- For limits and settings (pressure, torque, temperature), follow the manual if sources disagree.
- Never invent steps, values or part numbers. Do not add advice the sources don't give.
- If the sources do not answer the question, output exactly: NO_ANSWER

Language rule (overrides the source language): write every word of the answer in {lang} ({script}).
This includes the SAFETY: line and the CHECK: line. The sources and question excerpt may be in English,
but the answer must NOT be in English. If a source line is in English, translate that line; never copy an
English sentence into the answer. Only machine codes, part numbers, error codes, numbers and units stay in
English letters/digits."""


def answer_user(machine: dict | None, question_en: str, question_original: str | None, sources: list[dict],
                source_chars: int, already_tried: str | None = None, language: str | None = None) -> str:
    if machine:
        desc = " ".join(x for x in (machine.get("model"), machine.get("type")) if x)
        m = f"{machine['code']}" + (f" ({desc})" if desc else "")
    else:
        m = "not selected (any machine in the plant)"
    lines = [f"Machine: {m}", f"Question (English): {question_en.strip()[:500]}"]
    if language:
        lang, script = language_name(language), SCRIPT_HINT.get(language, "its usual script")
        lines.insert(0, f"Answer language: {lang} ({script}) — the answer must not be in English.")
    if question_original and question_original.strip() != question_en.strip():
        lines.append(f"Question as asked: {question_original.strip()[:500]}")
    if already_tried:
        lines.append(f"Already tried by the technician: {already_tried.strip()[:300]} "
                     "(don't give it as a first step again unless a source says it must be redone a specific way)")
    lines.append("")
    lines.append("Sources:")
    for s in sources:
        tag = " (same machine)" if s.get("same_machine") else ""
        text = " ".join((s.get("_text") or "").split())[:source_chars]
        lines.append(f"[{s['ref']}] {s.get('title') or ''}{tag}")
        lines.append(text)
        lines.append("")
    if language:
        lines.append(f"Remember: write the whole answer in {language_name(language)} ({SCRIPT_HINT.get(language, 'its usual script')}), not English. "
                     "Only codes, numbers and units stay in English.")
    return "\n".join(lines).strip()


QUESTION_EN_SYSTEM = """Translate a factory technician's spoken repair question into clear English for a search engine.
The text may mix an Indian language with English words (Hinglish etc.).
Keep machine codes, part numbers, error codes, numbers and units exactly (HP-07, E-05, 210 bar).
Keep sound words like thak-thak or khat-khat as they are. Do not answer the question."""

QUESTION_EN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["question_en"],
    "properties": {"question_en": {"type": "string"}},
}

def to_language_system(language: str) -> str:
    return (f"Translate this short message from a senior technician into simple spoken {language_name(language)}. "
            "Keep machine codes, part numbers, error codes, numbers and units exactly. Output only the translation.")


ANSWER_EN_SYSTEM ="""Translate this repair answer into simple English.
Keep every line, the line starts (SAFETY:, CHECK:, step numbers) and every [E1]/[M1]/[H1] ref exactly where they are.
Keep machine codes, part numbers, error codes, numbers and units exactly. Output only the translated text."""
