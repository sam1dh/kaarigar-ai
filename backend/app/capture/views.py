"""Turn DB rows into API responses."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

NON_RETRYABLE = {"no_speech", "too_short", "too_long", "bad_audio"}
PROCESSING = ("queued", "transcribing", "extracting", "checking", "translating")


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return str(v) if v is not None and not isinstance(v, (str, int, float, bool, dict, list)) else v


def record_view(rec: dict, *, viewer_id: str, viewer_role: str,
                signed_url: Callable[[str], str | None] | None = None, include_audio: bool = True) -> dict:
    is_author = str(rec["author_id"]) == viewer_id
    status, stage, err = rec["status"], rec.get("stage"), rec.get("error")
    failed = stage == "failed"
    fields = rec.get("fields") or {}
    return {
        "id": str(rec["id"]),
        "machine": {"id": str(rec["machine_id"]), "code": rec["machine_code"], "name": rec.get("machine_name"),
                    "line": rec.get("machine_line"), "model": rec.get("machine_model")},
        "author": {"id": str(rec["author_id"]), "name": rec.get("author_name")},
        "reviewer": {"id": str(rec["reviewed_by"]), "name": rec.get("reviewer_name")} if rec.get("reviewed_by") else None,
        "status": status,
        "stage": stage,
        "processing": stage in PROCESSING,
        "error": {"code": err, "retryable": err not in NON_RETRYABLE} if failed and err else None,
        "language": rec.get("language") or "en-IN",
        "audio_seconds": _iso(rec.get("audio_seconds")),
        "audio_url": signed_url(rec["audio_path"]) if (include_audio and signed_url and rec.get("audio_path")) else None,
        "transcript_en": rec.get("transcript_en"),
        "fields": {k: fields.get(k) for k in ("symptom", "cause", "fix", "steps", "parts", "tools",
                                             "safety_note", "downtime_min", "missing", "is_repair_note")},
        "links": fields.get("links"),
        "fields_local": rec.get("fields_local"),
        "ai_check": rec.get("ai_check"),
        "reject_reason": rec.get("reject_reason"),
        "edited_by_expert": rec.get("edited_by_expert"),
        "edited_by_reviewer": rec.get("edited_by_reviewer"),
        "created_at": _iso(rec.get("created_at")),
        "submitted_at": _iso(rec.get("submitted_at")),
        "reviewed_at": _iso(rec.get("reviewed_at")),
        "can": {
            "submit": is_author and status == "expert_review" and stage == "ready",
            "retry": is_author and failed and err not in NON_RETRYABLE,
            "discard": is_author and status in ("draft", "expert_review"),
            "review": viewer_role == "supervisor" and status == "pending" and not is_author,
        },
    }


def queue_item(rec: dict) -> dict:
    f = rec.get("fields") or {}
    chk = rec.get("ai_check") or {}
    issues = chk.get("issues") or []
    return {
        "id": str(rec["id"]),
        "machine": {"code": rec["machine_code"], "name": rec.get("machine_name")},
        "author": {"id": str(rec["author_id"]), "name": rec.get("author_name")},
        "submitted_at": _iso(rec.get("submitted_at")),
        "symptom": f.get("symptom"),
        "fix": f.get("fix"),
        "language": rec.get("language"),
        "audio_seconds": _iso(rec.get("audio_seconds")),
        "issues_high": sum(1 for i in issues if i.get("severity") == "high"),
        "issues_total": len(issues),
        "safety_ok": chk.get("safety_ok"),
    }
