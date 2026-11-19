"""Rows -> API responses for Phase 4."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any


def iso(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _num(v: Any, digits: int | None = None) -> float | int | None:
    if v is None:
        return None
    f = float(v)
    if digits is None:
        return int(round(f)) if f.is_integer() else f
    return round(f, digits)


def person_view(r: dict, *, viewer_id: str) -> dict:
    last = max([d for d in (r.get("last_sign_in_at"), r.get("last_question_at"), r.get("last_note_at")) if d],
               default=None)
    if r.get("deactivated_at"):
        status = "deactivated"
    elif not r.get("last_sign_in_at") and not last:
        status = "new"
    else:
        status = "active"
    login = "pin" if r["role"] in ("technician", "expert") else "email"
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "employee_id": r.get("employee_id"),
        "email": r.get("email") if login == "email" else None,
        "role": r["role"],
        "is_admin": bool(r.get("is_admin")),
        "language": r.get("language"),
        "login": login,
        "status": status,
        "last_active": iso(last),
        "approved_notes": int(r.get("approved_notes") or 0),
        "created_at": iso(r.get("created_at")),
        "deactivated_at": iso(r.get("deactivated_at")),
        "is_you": str(r["id"]) == viewer_id,
    }


def machine_view(r: dict, *, public_url: str) -> dict:
    return {
        "id": str(r["id"]),
        "code": r["code"],
        "name": r.get("name"),
        "line": r.get("line"),
        "model": {"id": str(r["model_id"]), "model": r.get("model"), "type": r.get("type"), "oem": r.get("oem")}
        if r.get("model_id") else None,
        "approved_records": int(r.get("approved_records") or 0),
        "questions_30d": int(r.get("questions_30d") or 0),
        "last_breakdown": {"date": iso(r.get("last_breakdown_date")), "fault": r.get("last_breakdown_fault")}
        if r.get("last_breakdown_date") or r.get("last_breakdown_fault") else None,
        "qr_url": f"{public_url.rstrip('/')}/m/{r['qr_token']}",
        "sticker_printed_at": iso(r.get("sticker_printed_at")),
        "archived": r.get("archived_at") is not None,
        "archived_at": iso(r.get("archived_at")),
    }


def record_item(r: dict) -> dict:
    f = r.get("fields") or {}
    symptom, fix = f.get("symptom"), f.get("fix")
    title = " → ".join(x for x in (symptom, fix) if x) or "Repair record"
    return {
        "kind": "E", "source_type": "record", "id": str(r["id"]), "title": title,
        "machine": r.get("machine_code"), "author": r.get("author_name"), "approved_by": r.get("reviewer_name"),
        "date": iso(r.get("reviewed_at") or r.get("created_at")), "used": int(r.get("used") or 0),
        "status": "archived" if r.get("archived_at") else "ready", "origin": r.get("source"),
    }


def document_item(r: dict) -> dict:
    status = r.get("status")
    shown = {"ready": "ready", "failed": "failed"}.get(status, "processing")
    if status == "ready" and r.get("quality_notes"):
        shown = "low_text_quality"
    return {
        "kind": "M", "source_type": "manual", "id": str(r["id"]), "title": r["title"], "machine": None,
        "doc_type": r.get("type"), "model": r.get("model"), "pages": r.get("pages"),
        "sections": int(r.get("sections") or 0), "quality_notes": r.get("quality_notes"),
        "date": iso(r.get("created_at")), "used": int(r.get("used") or 0), "status": shown,
    }


def log_item(r: dict) -> dict:
    title = " → ".join(x for x in (r.get("fault"), r.get("action")) if x) or "Breakdown"
    return {
        "kind": "H", "source_type": "log", "id": str(r["id"]), "title": title, "machine": r.get("machine_code"),
        "date": iso(r.get("date") or r.get("created_at")), "downtime_min": r.get("downtime_min"),
        "technician": r.get("technician"), "used": int(r.get("used") or 0), "status": "ready",
    }


def analytics_view(a: dict, days: int) -> dict:
    t, fb, esc, notes = a["totals"], a["feedback"], a["escalations"], a["notes"]
    questions = int(t.get("questions") or 0)
    answered = int(t.get("answered") or 0)
    return {
        "days": days,
        "questions": {
            "total": questions, "answered": answered, "no_answer": int(t.get("no_answer") or 0),
            "failed": int(t.get("failed") or 0), "voice": int(t.get("voice") or 0),
            "escalated": int(t.get("escalated") or 0),
            "answered_rate": round(answered / questions, 3) if questions else None,
            "first_word_ms": _num(t.get("first_word_ms"), 0),
        },
        "feedback": {"fixed": int(fb.get("fixed") or 0), "not_fixed": int(fb.get("not_fixed") or 0),
                     "total": int(fb.get("feedback") or 0)},
        "escalations": {"created": int(esc.get("created") or 0), "answered": int(esc.get("answered") or 0),
                        "open_now": int(esc.get("open_now") or 0),
                        "minutes_to_answer": _num(esc.get("minutes_to_answer"), 0)},
        "notes": {"sent": int(notes.get("sent") or 0), "approved": int(notes.get("approved") or 0),
                  "rejected": int(notes.get("rejected") or 0), "pending_now": int(notes.get("pending_now") or 0),
                  "hours_to_review": _num(notes.get("hours_to_review"), 1)},
        "per_day": [{"day": iso(d["day"]), "questions": int(d["questions"]), "answered": int(d["answered"]),
                     "escalated": int(d["escalated"])} for d in a["per_day"]],
        "machines": [{"code": m["code"], "name": m.get("name"), "questions": int(m["questions"]),
                      "no_answer": int(m["no_answer"]), "escalated": int(m["escalated"])} for m in a["machines"]],
        "gaps": [{"id": str(g["id"]), "question": g.get("question_en") or g.get("question_original"),
                  "status": g["status"], "machine": g.get("machine_code"), "created_at": iso(g["created_at"]),
                  "escalation_status": g.get("escalation_status")} for g in a["gaps"]],
        "team": [{"id": str(p["id"]), "name": p["name"], "role": p["role"], "questions": int(p["questions"]),
                  "notes_sent": int(p["notes_sent"]), "notes_approved": int(p["notes_approved"]),
                  "answers_given": int(p["answers_given"]), "knowledge_used": int(p["knowledge_used"])}
                 for p in a["team"]],
    }
