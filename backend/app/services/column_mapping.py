"""Excel column → field mapping: rules always; LLM only when GROQ_API_KEY is set.

A header maps to one field only; first match wins in the field order below.
"""

from __future__ import annotations

import json
import logging

from app.core.config import get_settings

logger = logging.getLogger("kaarigar.mapping")

FIELDS = ["machine_code", "date", "fault", "action", "downtime_min", "technician"]

RULES: dict[str, list[str]] = {
    "machine_code": ["m/c", "mc no", "machine", "mach", "equipment", "asset", "मशीन"],
    "date": ["date", "dt", "day", "तारीख", "dinank"],
    "fault": ["problem", "breakdown", "fault", "issue", "complaint", "defect", "samasya", "समस्या"],
    "action": ["action", "kya kiya", "work done", "remedy", "solution", "repair", "rectification"],
    "downtime_min": ["down time", "downtime", "stoppage", "time lost", "duration", "minutes", "hrs"],
    "technician": ["attended", "technician", "done by", "name", "fitter", "engineer"],
}


def rules_mapping(columns: list[str]) -> dict[str, str | None]:
    """Keyword rules. Each column used at most once; field order decides."""
    mapping: dict[str, str | None] = {f: None for f in FIELDS}
    used: set[str] = set()
    for field in FIELDS:
        for col in columns:
            if col in used:
                continue
            low = str(col).lower()
            if any(kw in low for kw in RULES[field]):
                mapping[field] = col
                used.add(col)
                break
    return mapping


def llm_mapping(columns: list[str], sample_rows: list[dict]) -> tuple[dict[str, str | None], str] | None:
    """Groq call. Returns (mapping, 'llm') or None to fall back to rules."""
    s = get_settings()
    if not s.groq_api_key:
        return None

    properties = {
        f: {"type": ["string", "null"], "enum": [*columns, None]} for f in FIELDS
    }
    properties["notes"] = {"type": "string"}
    schema = {
        "type": "object",
        "properties": properties,
        "required": [*FIELDS, "notes"],
        "additionalProperties": False,
    }

    prompt = (
        "Map each Excel column to one field of a machine breakdown register, or null.\n"
        "Fields: machine_code (required), date (required), fault (required), action, "
        "downtime_min, technician. Headers may be Hinglish.\n"
        f"Columns: {json.dumps(columns)}\n"
        f"Sample rows: {json.dumps(sample_rows, default=str)}\n"
        'Answer JSON with keys machine_code, date, fault, action, downtime_min, technician, notes.'
    )

    import httpx

    try:
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {s.groq_api_key}"},
            json={
                "model": s.groq_model_small,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "reasoning_effort": "low",
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "column_mapping", "strict": True, "schema": schema},
                },
            },
            timeout=15,
        )
        if r.status_code == 429:
            retry = r.headers.get("retry-after")
            if retry:
                import time

                time.sleep(min(float(retry), 5))
            r = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {s.groq_api_key}"},
                json={
                    "model": s.groq_model_small,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "reasoning_effort": "low",
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "column_mapping", "strict": True, "schema": schema},
                    },
                },
                timeout=15,
            )
        if r.status_code != 200:
            logger.info("groq mapping unavailable: HTTP %s", r.status_code)
            return None
        data = json.loads(r.json()["choices"][0]["message"]["content"])
        mapping: dict[str, str | None] = {}
        for f in FIELDS:
            col = data.get(f)
            if col not in columns:
                return None  # unknown column → fall back
            mapping[f] = col
        for f in ("machine_code", "date", "fault"):
            if mapping[f] is None:
                return None  # required fields must be mapped
        return mapping, "llm"
    except Exception as e:
        logger.info("groq mapping failed, using rules: %s", type(e).__name__)
        return None


def suggest_mapping(columns: list[str], sample_rows: list[dict]) -> tuple[dict[str, str | None], str]:
    got = llm_mapping(columns, sample_rows)
    if got:
        return got
    return rules_mapping(columns), "rules"
