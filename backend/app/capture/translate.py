"""English <-> the expert's language for the 'Check your note' screen (gpt-oss-20b)."""
from __future__ import annotations

from .languages import is_english, language_name
from .llm import GroqLLM
from .prompts import translate_system, translate_user
from .schemas import TRANSLATION_SCHEMA, TRANSLATABLE_KEYS, Translated


def _payload(fields: dict, issues: list[str] | None = None, summary: str | None = None) -> dict:
    return {
        "symptom": fields.get("symptom"),
        "cause": fields.get("cause"),
        "fix": fields.get("fix"),
        "steps": list(fields.get("steps") or []),
        "safety_note": fields.get("safety_note"),
        "issues": list(issues or []),
        "summary": summary,
    }


def to_local(llm: GroqLLM, model: str, fields: dict, ai_check: dict | None, target: str) -> dict | None:
    """Translate the displayable fields + AI messages into `target`. Returns None for English."""
    if is_english(target):
        return None
    issues = [i["message"] for i in (ai_check or {}).get("issues", [])]
    summary = (ai_check or {}).get("summary")
    out = llm.structured(
        model=model, system=translate_system(language_name(target)),
        user=translate_user(_payload(fields, issues, summary)),
        schema_name="translation", schema=TRANSLATION_SCHEMA, out=Translated, max_tokens=2000,
    )
    data = out.model_dump()
    # Guard against the model dropping items: fall back to English item by item
    if len(data["steps"]) != len(fields.get("steps") or []):
        data["steps"] = list(fields.get("steps") or [])
    if len(data["issues"]) != len(issues):
        data["issues"] = issues
    data["language"] = target
    return data


def edits_to_english(llm: GroqLLM, model: str, edits: dict, source: str) -> dict:
    """Translate only the edited translatable keys back to English. Other keys pass through unchanged."""
    if is_english(source):
        return dict(edits)
    to_translate = {k: edits[k] for k in TRANSLATABLE_KEYS if k in edits and edits[k]}
    if not to_translate:
        return dict(edits)
    out = llm.structured(
        model=model, system=translate_system("English"),
        user=translate_user(_payload(to_translate)),
        schema_name="translation", schema=TRANSLATION_SCHEMA, out=Translated, max_tokens=1500,
    ).model_dump()
    result = dict(edits)
    for k in to_translate:
        val = out.get(k)
        if k == "steps":
            if isinstance(val, list) and len(val) == len(to_translate[k]):
                result[k] = val
        elif val:
            result[k] = val
    return result
