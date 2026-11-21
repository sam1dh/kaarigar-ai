"""DB rows -> API responses for Phase 3."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

FIELD_KEYS = ("symptom", "cause", "fix", "steps", "safety_note")


def _iso(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _person(pid: Any, name: Any) -> dict | None:
    return {"id": str(pid), "name": name} if pid else None


def _machine(row: dict) -> dict | None:
    if not row.get("machine_code"):
        return None
    return {"code": row["machine_code"], "name": row.get("machine_name"), "model": row.get("machine_model"),
            "line": row.get("machine_line")}


def query_view(row: dict, *, viewer_id: str, escalate_below: float) -> dict:
    status = row.get("status") or "answered"
    final = status in ("answered", "no_answer", "failed")
    is_owner = str(row["user_id"]) == viewer_id
    conf = row.get("confidence")
    esc = None
    if row.get("escalation_id"):
        esc = {"id": str(row["escalation_id"]), "status": row.get("escalation_status"),
               "assigned_to": _person(row.get("escalation_assigned_to"), row.get("escalation_assigned_name")),
               "answered_at": _iso(row.get("escalation_answered_at"))}
    return {
        "id": str(row["id"]),
        "status": status,
        "created_at": _iso(row.get("created_at")),
        "machine": _machine(row),
        "language": row.get("language"),
        "input_mode": row.get("input_mode"),
        "question": {"original": row.get("question_original"), "en": row.get("question_en")},
        "answer": {"parts": row.get("answer_parts"), "text": row.get("answer_local"),
                   "en": row.get("answer")},
        "sources": row.get("sources") or [],
        "confidence": float(conf) if conf is not None else None,
        "suggest_escalate": status in ("no_answer", "failed") or (conf is not None and float(conf) < escalate_below),
        "latency_ms": row.get("latency_ms"),
        "first_token_ms": row.get("first_token_ms"),
        "error": {"code": row["error"]} if status == "failed" and row.get("error") else None,
        "feedback": row.get("feedback"),
        "escalation": esc,
        "asked_by": _person(row.get("user_id"), row.get("user_name")),
        "can": {
            "feedback": is_owner and status in ("answered", "no_answer"),
            "escalate": is_owner and final and not esc,
            "read_aloud": is_owner and status == "answered",
        },
    }


def query_list_item(row: dict, *, escalate_below: float) -> dict:
    v = query_view(row, viewer_id=str(row["user_id"]), escalate_below=escalate_below)
    parts = v["answer"]["parts"] or {}
    steps = parts.get("steps") or []
    return {
        "id": v["id"], "status": v["status"], "created_at": v["created_at"], "machine": v["machine"],
        "question": v["question"], "first_step": steps[0]["text"] if steps else None,
        "feedback": v["feedback"], "escalation": v["escalation"],
    }


def reply_record_view(row: dict, signed_url: Callable[[str], str | None] | None) -> dict | None:
    if not row.get("reply_record_id"):
        return None
    fields = row.get("reply_fields") or {}
    return {
        "id": str(row["reply_record_id"]),
        "status": row.get("reply_record_status"),
        "stage": row.get("reply_record_stage"),
        "language": row.get("reply_language"),
        "fields": {k: fields.get(k) for k in FIELD_KEYS},
        "audio_url": signed_url(row["reply_audio_path"]) if (signed_url and row.get("reply_audio_path")) else None,
    }


def escalation_item(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "created_at": _iso(row.get("created_at")),
        "answered_at": _iso(row.get("answered_at")),
        "closed_at": _iso(row.get("closed_at")),
        "machine": _machine(row),
        "asked_by": _person(row.get("asked_by"), row.get("asked_by_name")),
        "assigned_to": _person(row.get("assigned_to"), row.get("assigned_name")),
        "replied_by": _person(row.get("replied_by"), row.get("replied_name")),
        "question": {"original": row.get("question_original"), "en": row.get("question_en"),
                     "language": row.get("question_language")},
        "answer_status": row.get("answer_status"),
        "feedback": row.get("feedback"),
        "has_note": bool(row.get("note")),
        "reply_in_progress": bool(row.get("reply_record_id")) and row["status"] == "open",
    }


def escalation_view(row: dict, *, signed_url: Callable[[str], str | None] | None = None) -> dict:
    base = escalation_item(row)
    conf = row.get("confidence")
    base.update({
        "query_id": str(row["query_id"]),
        "note": row.get("note"),
        "close_reason": row.get("close_reason"),
        "assigned_at": _iso(row.get("assigned_at")),
        "kaarigar": {
            "status": row.get("answer_status"),
            "answer_en": row.get("answer"),
            "answer_local": row.get("answer_local"),
            "parts": row.get("answer_parts"),
            "sources": row.get("sources") or [],
            "confidence": float(conf) if conf is not None else None,
            "asked_at": _iso(row.get("asked_at")),
        },
        "reply": {
            "text": row.get("reply_text"),
            "record": reply_record_view(row, signed_url),
        },
    })
    return base


def record_source_view(row: dict, *, local: dict | None, signed_url: Callable[[str], str | None] | None) -> dict:
    fields = row.get("fields") or {}
    return {
        "type": "record",
        "id": str(row["id"]),
        "machine": _machine(row),
        "author": {"id": str(row["author_id"]), "name": row.get("author_name")},
        "approved_by": row.get("reviewer_name"),
        "date": _iso(row.get("reviewed_at") or row.get("created_at")),
        "status": row.get("status"),
        "language": row.get("language"),
        "fields": {k: fields.get(k) for k in FIELD_KEYS},
        "local": local,
        "audio_url": signed_url(row["audio_path"]) if (signed_url and row.get("audio_path")) else None,
        "audio_seconds": _iso(row.get("audio_seconds")),
    }


def manual_source_view(doc: dict, *, page: int | None, pdf_url: str | None) -> dict:
    chunks = doc.get("chunks") or []
    return {
        "type": "manual",
        "id": str(doc["id"]),
        "title": doc.get("title"),
        "model": doc.get("model"),
        "page": page,
        "pages": doc.get("pages"),
        "sections": [{"section": c.get("section"), "text": c.get("text"), "page": c.get("page")} for c in chunks],
        "pdf_url": (f"{pdf_url}#page={page}" if (pdf_url and page) else pdf_url),
    }


def log_source_view(row: dict) -> dict:
    return {
        "type": "log",
        "id": str(row["id"]),
        "machine": _machine(row),
        "date": _iso(row.get("date")),
        "fault": row.get("fault"),
        "action": row.get("action"),
        "downtime_min": row.get("downtime_min"),
        "technician": row.get("technician"),
    }
