"""Data shapes for Phase 2.

Each LLM output has a Pydantic model (used to validate) and a hand-written JSON schema
(strict-mode compatible: every property required, additionalProperties false, nullable via type lists).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Repair record fields (English, stored in repair_records.fields)

EDITABLE_KEYS = ("symptom", "cause", "fix", "steps", "parts", "tools", "safety_note", "downtime_min")
TRANSLATABLE_KEYS = ("symptom", "cause", "fix", "steps", "safety_note")
MISSING_ENUM = ["symptom", "cause", "fix", "steps", "safety_note"]


class Part(BaseModel):
    name: str
    part_no: str | None = None
    qty: float | None = None


class Extraction(BaseModel):
    """What gpt-oss-20b pulls out of the English transcript."""

    is_repair_note: bool
    symptom: str | None = None
    cause: str | None = None
    fix: str | None = None
    steps: list[str] = Field(default_factory=list)
    parts: list[Part] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    safety_note: str | None = None
    downtime_min: int | None = None
    missing: list[Literal["symptom", "cause", "fix", "steps", "safety_note"]] = Field(default_factory=list)

    @field_validator("symptom", "cause", "fix", "safety_note")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @field_validator("steps", "tools")
    @classmethod
    def _clean_list(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s and s.strip()][:20]


_nullable_str = {"type": ["string", "null"]}
EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_repair_note", "symptom", "cause", "fix", "steps", "parts", "tools",
                 "safety_note", "downtime_min", "missing"],
    "properties": {
        "is_repair_note": {"type": "boolean"},
        "symptom": _nullable_str,
        "cause": _nullable_str,
        "fix": _nullable_str,
        "steps": {"type": "array", "items": {"type": "string"}},
        "parts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "part_no", "qty"],
                "properties": {"name": {"type": "string"}, "part_no": _nullable_str,
                               "qty": {"type": ["number", "null"]}},
            },
        },
        "tools": {"type": "array", "items": {"type": "string"}},
        "safety_note": _nullable_str,
        "downtime_min": {"type": ["integer", "null"]},
        "missing": {"type": "array", "items": {"type": "string", "enum": MISSING_ENUM}},
    },
}

# ---------------------------------------------------------------------------
# AI check (gpt-oss-120b)

IssueField = Literal["symptom", "cause", "fix", "steps", "parts", "safety_note", "general"]


class Issue(BaseModel):
    field: IssueField
    severity: Literal["high", "medium", "low"]
    message: str


class AICheck(BaseModel):
    issues: list[Issue] = Field(default_factory=list)
    safety_ok: bool
    summary: str

    @field_validator("issues")
    @classmethod
    def _cap(cls, v: list[Issue]) -> list[Issue]:
        return v[:8]


AI_CHECK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["issues", "safety_ok", "summary"],
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "severity", "message"],
                "properties": {
                    "field": {"type": "string", "enum": list(IssueField.__args__)},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "message": {"type": "string"},
                },
            },
        },
        "safety_ok": {"type": "boolean"},
        "summary": {"type": "string"},
    },
}

# ---------------------------------------------------------------------------
# Translation (gpt-oss-20b), same shape both directions


class Translated(BaseModel):
    symptom: str | None = None
    cause: str | None = None
    fix: str | None = None
    steps: list[str] = Field(default_factory=list)
    safety_note: str | None = None
    issues: list[str] = Field(default_factory=list)
    summary: str | None = None


TRANSLATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["symptom", "cause", "fix", "steps", "safety_note", "issues", "summary"],
    "properties": {
        "symptom": _nullable_str,
        "cause": _nullable_str,
        "fix": _nullable_str,
        "steps": {"type": "array", "items": {"type": "string"}},
        "safety_note": _nullable_str,
        "issues": {"type": "array", "items": {"type": "string"}},
        "summary": _nullable_str,
    },
}

# ---------------------------------------------------------------------------
# API bodies


class FieldEdits(BaseModel):
    """Any subset of the editable fields. Unknown keys are rejected."""

    model_config = {"extra": "forbid"}

    symptom: str | None = Field(default=None, max_length=200)
    cause: str | None = Field(default=None, max_length=300)
    fix: str | None = Field(default=None, max_length=300)
    steps: list[str] | None = Field(default=None, max_length=20)
    parts: list[Part] | None = Field(default=None, max_length=20)
    tools: list[str] | None = Field(default=None, max_length=20)
    safety_note: str | None = Field(default=None, max_length=500)
    downtime_min: int | None = Field(default=None, ge=0, le=10000)


class SubmitBody(BaseModel):
    """Expert presses 'Send to supervisor'.

    `edits` holds only the fields the expert changed, written in `edit_language`
    (the language shown on screen). The backend translates them to English if needed.
    """

    edits: FieldEdits = Field(default_factory=FieldEdits)
    edit_language: str = "en-IN"


class ApproveBody(BaseModel):
    edits: FieldEdits = Field(default_factory=FieldEdits)   # supervisor edits are in English


class RejectBody(BaseModel):
    reason: str = Field(min_length=5, max_length=500)
