"""Prompts for the capture pipeline. Kept short: Groq free tier is ~8k tokens/min per model."""
import json

EXTRACT_SYSTEM = """You turn a shop-floor technician's spoken repair note into a structured repair record.
The note was spoken in an Indian language and machine-translated to English, so expect rough grammar,
Hinglish words and numbers said in words.

Rules:
- Use ONLY what the technician said. Never invent causes, parts, values or safety steps.
- symptom: what was wrong, as a short label (3-8 words), e.g. "pressure not building".
- cause: why it happened, short label (3-10 words). null if not said.
- fix: what was done to fix it, short label (3-10 words). null if not said.
- steps: the repair steps in order, each one short sentence. Empty list if none.
- parts: parts replaced or used, with part number and quantity only if said.
- tools: special tools or instruments mentioned (test gauge, dial indicator...).
- safety_note: any safety precaution the technician mentioned, as one sentence. null if none.
- downtime_min: total downtime in minutes only if said, else null.
- missing: which of symptom, cause, fix, steps, safety_note were NOT said.
- is_repair_note: false if this is not about fixing a machine (chit-chat, silence, a question).
- Keep machine codes, part numbers, error codes and units exactly (E-05, SK-200-R, 210 bar).
- Glossary words may appear; their meanings are given."""


def extract_user(machine: dict, transcript_en: str, glossary: list[dict]) -> str:
    gl = ", ".join(f"{g['term']} = {g['meaning']}" for g in glossary[:30]) or "none"
    return (
        f"Machine: {machine['code']} ({machine.get('model') or '?'} {machine.get('type') or ''}).\n"
        f"Glossary: {gl}\n\n"
        f"Transcript (English):\n\"\"\"\n{transcript_en[:6000]}\n\"\"\""
    )


CHECK_SYSTEM = """You are a senior maintenance engineer reviewing a junior colleague's repair record before it
becomes part of the plant's knowledge base. Be practical and brief.

Flag only real problems:
- high: unsafe advice, a safety step clearly needed but missing (work on pressurised hydraulics, electrics,
  rotating parts, hot oil), a fix that contradicts the manual excerpts, or a record that is not a repair at all.
- medium: cause or fix missing or vague, steps out of order, values that look wrong.
- low: small clarity issues.
Write each message as one plain sentence the technician can act on (max 20 words).
safety_ok: true only if the record mentions the safety precautions this kind of job needs (or none are needed).
summary: one sentence describing the repair.
Return an empty issues list if the record is good."""


def check_user(machine: dict, fields: dict, transcript_en: str, manual_excerpts: list[dict]) -> str:
    rec = {k: fields.get(k) for k in ("symptom", "cause", "fix", "steps", "parts", "safety_note", "downtime_min")}
    excerpts = "\n\n".join(
        f"[{e.get('title', 'Manual')}]\n{e.get('text', '')[:700]}" for e in manual_excerpts
    ) or "(no manual excerpts found)"
    return (
        f"Machine: {machine['code']} ({machine.get('model') or '?'} {machine.get('type') or ''}).\n\n"
        f"Record:\n{json.dumps(rec, ensure_ascii=False)}\n\n"
        f"Transcript:\n\"\"\"\n{transcript_en[:3000]}\n\"\"\"\n\n"
        f"Manual excerpts for this machine model:\n{excerpts}"
    )


def translate_system(target_language: str) -> str:
    return f"""Translate the JSON values into {target_language} for a factory technician.
Use simple, spoken {target_language}, not formal or literary language.
Keep machine codes, part numbers, error codes, numbers and units exactly as they are (HP-07, SK-200-R, E-05, 210 bar).
Keep common English shop-floor words that technicians use (seal, valve, pump, filter, bar) in English.
Return every key. Keep null as null and keep list lengths the same."""


def translate_user(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)
