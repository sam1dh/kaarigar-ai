"""/assist/* — the technician's side (phone). Anyone signed in can ask."""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.capture.audio import extension_for

from . import answer_format as af
from .adapters import AssistUser, assist_user
from .errors import AssistError, api_error
from .pipeline import AskRequest
from .service import AssistService, get_service
from .streaming import SSE_HEADERS, run_as_sse
from .views import (escalation_view, log_source_view, manual_source_view, query_list_item, query_view,
                    record_source_view)

router = APIRouter(prefix="/assist", tags=["assist"])

AUDIO_EXT_BY_NAME = {"webm": "webm", "ogg": "ogg", "m4a": "m4a", "mp4": "m4a", "mp3": "mp3", "wav": "wav", "aac": "aac"}


class FeedbackBody(BaseModel):
    outcome: Literal["fixed", "not_fixed", "call_supervisor"]


class EscalateBody(BaseModel):
    note: str | None = Field(default=None, max_length=500)


def _uuid(value: str, what: str = "id") -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise api_error(422, "invalid_id", f"Not a valid {what}.")


def _machine_out(m: dict) -> dict:
    return {"code": m["code"], "name": m.get("name"), "line": m.get("line"), "model": m.get("model"),
            "type": m.get("type")}


# ---------------------------------------------------------------------------- ask (SSE)

@router.post("/ask")
async def ask(
    machine_code: Annotated[str | None, Form(max_length=40)] = None,
    text: Annotated[str | None, Form()] = None,
    audio: Annotated[UploadFile | None, File()] = None,
    user: AssistUser = Depends(assist_user),
    svc: AssistService = Depends(get_service),
):
    s = svc.settings
    if not svc.ask_limit.allow(user.id):
        raise api_error(429, "rate_limited", "You're asking very fast. Wait a minute and try again.")
    if (text is None) == (audio is None):
        raise api_error(422, "question_required", "Send a recording or type a question.")

    machine = None
    if machine_code and machine_code.strip():
        machine = await run_in_threadpool(svc.repo.machine_by_code, user.tenant_id, machine_code)
        if not machine:
            raise api_error(404, "machine_not_found", "Machine not found.")

    data: bytes | None = None
    ext = None
    if text is not None:
        text = " ".join(text.split())
        if not (3 <= len(text) <= s.MAX_QUESTION_CHARS):
            raise api_error(422, "bad_question", f"Type a question of 3 to {s.MAX_QUESTION_CHARS} characters.")
    else:
        assert audio is not None
        ext = extension_for(audio.content_type)
        if not ext and audio.filename and "." in audio.filename:
            ext = AUDIO_EXT_BY_NAME.get(audio.filename.rsplit(".", 1)[-1].lower())
        if not ext:
            raise api_error(415, "unsupported_audio", "Send a webm, ogg, m4a, mp3, aac or wav recording.")
        limit = int(s.ASSIST_MAX_AUDIO_MB * 1024 * 1024)
        data = await audio.read(limit + 1)
        if len(data) > limit:
            raise api_error(413, "audio_too_big", f"Recording is larger than {s.ASSIST_MAX_AUDIO_MB:g} MB.")
        if len(data) < 500:
            raise api_error(422, "audio_empty", "The recording is empty.")

    query_id = str(uuid.uuid4())
    await run_in_threadpool(
        svc.repo.create_query, query_id=query_id, tenant_id=user.tenant_id, user_id=user.id,
        machine_id=str(machine["id"]) if machine else None, language=user.language,
        input_mode="text" if text is not None else "voice", audio_path=None,
        question_original=text,
    )
    req = AskRequest(query_id=query_id, tenant_id=user.tenant_id, user_id=user.id, language=user.language,
                     machine=machine, text=text, audio=data)
    content_type = (audio.content_type if audio else None) or "application/octet-stream"
    superseded = svc.begin_run(user.id)     # an older answer still running for this person stops now

    def work(emit, cancelled):
        try:
            if data is not None:
                path = f"{user.tenant_id}/questions/{query_id}.{ext}"    # never built from the user's file name
                try:
                    svc.storage.upload("audio", path, data, content_type)
                    svc.repo.update_query(user.tenant_id, query_id, audio_path=path)
                except Exception:  # noqa: BLE001  keeping the recording is nice to have, not required
                    pass
            return svc.pipeline.run(req, emit, lambda: cancelled() or superseded.is_set())
        finally:
            svc.end_run(user.id, superseded)

    def rejected():
        svc.repo.update_query(user.tenant_id, query_id, status="failed", error="server_restarted")

    stream = run_as_sse(svc.executor, work, ping_sec=s.SSE_PING_SEC, on_reject=rejected,
                        first=[("meta", {"query_id": query_id, "machine": _machine_out(machine) if machine else None}),
                               ("stage", {"stage": "queued"})])
    return StreamingResponse(stream, media_type="text/event-stream", headers=SSE_HEADERS)


# ---------------------------------------------------------------------------- my questions

def _load_query(svc: AssistService, user: AssistUser, query_id: str) -> dict:
    row = svc.repo.get_query(user.tenant_id, _uuid(query_id, "question id"))
    if not row:
        raise api_error(404, "not_found", "Question not found.")
    if str(row["user_id"]) == user.id or user.role == "supervisor":
        return row
    if user.role == "expert" and row.get("escalation_id") and (
            row.get("escalation_assigned_to") is None or str(row["escalation_assigned_to"]) == user.id):
        return row
    raise api_error(404, "not_found", "Question not found.")


@router.get("/queries")
def my_queries(limit: int = Query(20, ge=1, le=50), user: AssistUser = Depends(assist_user),
               svc: AssistService = Depends(get_service)):
    rows = svc.repo.list_queries(user.tenant_id, user.id, limit)
    return {"items": [query_list_item(r, escalate_below=svc.settings.ESCALATE_BELOW) for r in rows]}


def _escalation_for_asker(svc: AssistService, user: AssistUser, escalation_id: str) -> dict | None:
    row = svc.repo.get_escalation(user.tenant_id, escalation_id)
    if not row:
        return None
    view = escalation_view(row, signed_url=lambda p: svc.signed("audio", p))
    lang = row.get("asked_by_language") or user.language
    rec = view["reply"]["record"]
    local = None
    if rec or view["reply"]["text"]:
        cached = row.get("reply_local") or {}
        rec_key = rec["id"] if rec else None
        if cached.get("language") == lang and cached.get("record_id") == rec_key:
            local = cached
        else:
            local = {"language": lang, "record_id": rec_key, "fields": None, "text": None}
            if rec:
                if row.get("reply_language") == lang and row.get("reply_fields_local"):
                    local["fields"] = row["reply_fields_local"]
                else:
                    local["fields"] = svc.fields_in(f"rec:{rec['id']}", rec["fields"], lang)
            if view["reply"]["text"]:
                local["text"] = svc.text_in(f"esc:{row['id']}", view["reply"]["text"], lang)
            if local["fields"] or local["text"]:
                svc.repo.set_reply_local(user.tenant_id, str(row["id"]), local)
    view["reply"]["local"] = local
    return view


@router.get("/queries/{query_id}")
def get_query(query_id: str, user: AssistUser = Depends(assist_user), svc: AssistService = Depends(get_service)):
    row = _load_query(svc, user, query_id)
    view = query_view(row, viewer_id=user.id, escalate_below=svc.settings.ESCALATE_BELOW)
    if row.get("escalation_id"):
        view["escalation"] = _escalation_for_asker(svc, user, str(row["escalation_id"]))
    return view


@router.post("/queries/{query_id}/feedback")
def feedback(query_id: str, body: FeedbackBody, user: AssistUser = Depends(assist_user),
             svc: AssistService = Depends(get_service)):
    row = _load_query(svc, user, query_id)
    if str(row["user_id"]) != user.id:
        raise api_error(403, "not_owner", "Only the person who asked can give feedback.")
    if row["status"] not in ("answered", "no_answer"):
        raise api_error(409, "not_answered", "There's no answer to rate yet.")
    svc.repo.upsert_feedback(user.tenant_id, str(row["id"]), user.id, body.outcome)
    if body.outcome == "fixed" and row.get("escalation_status") == "open":
        svc.repo.close_open_for_query(user.tenant_id, str(row["id"]), "fixed_by_technician")
    return query_view(svc.repo.get_query(user.tenant_id, str(row["id"])), viewer_id=user.id,
                      escalate_below=svc.settings.ESCALATE_BELOW)


@router.post("/queries/{query_id}/escalate", status_code=201)
def escalate(query_id: str, body: EscalateBody, user: AssistUser = Depends(assist_user),
             svc: AssistService = Depends(get_service)):
    row = _load_query(svc, user, query_id)
    if str(row["user_id"]) != user.id:
        raise api_error(403, "not_owner", "Only the person who asked can send it to an expert.")
    if row["status"] not in ("answered", "no_answer", "failed"):
        raise api_error(409, "not_finished", "Wait for Kaarigar to finish answering.")
    if row.get("escalation_id"):
        raise api_error(409, "already_escalated", "This question was already sent to an expert.")
    expert_id = svc.repo.pick_expert(user.tenant_id, str(row["machine_id"]) if row.get("machine_id") else None,
                                     user.id)
    note = " ".join(body.note.split()) if body.note else None
    if not note:   # use what the technician said they already tried (from the understand step)
        note = ((row.get("answer_parts") or {}).get("understanding") or {}).get("already_tried")
    esc_id = svc.repo.create_escalation(tenant_id=user.tenant_id, query_id=str(row["id"]), asked_by=user.id,
                                        machine_id=str(row["machine_id"]) if row.get("machine_id") else None,
                                        note=note or None, assigned_to=expert_id)
    if not esc_id:
        raise api_error(409, "already_escalated", "This question was already sent to an expert.")
    expert = svc.repo.user_in_tenant(user.tenant_id, expert_id) if expert_id else None
    return {"escalation_id": esc_id, "assigned_to": {"id": expert_id, "name": expert["name"]} if expert else None}


@router.post("/queries/{query_id}/tts")
def read_aloud(query_id: str, user: AssistUser = Depends(assist_user), svc: AssistService = Depends(get_service)):
    row = _load_query(svc, user, query_id)
    if str(row["user_id"]) != user.id and user.role != "supervisor":
        raise api_error(403, "not_owner", "Not your question.")
    if row["status"] != "answered":
        raise api_error(409, "not_answered", "There's no answer to read.")
    path = f"{user.tenant_id}/{row['id']}.wav"
    try:
        wav = svc.storage.download("tts", path)
        if wav:
            return Response(content=wav, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})
    except Exception:  # noqa: BLE001  not cached yet
        pass
    if not svc.tts_limit.allow(user.id):
        raise api_error(429, "rate_limited", "Wait a minute before playing more answers.")
    parsed = af.parse_answer(row.get("answer_local") or "")
    text = af.speakable(parsed)
    if not text:
        raise api_error(409, "not_answered", "There's no answer to read.")
    try:
        wav = svc.tts_factory().synthesize(text, row.get("language") or user.language)
    except AssistError as e:
        raise api_error(503, e.code, e.user_message)
    try:
        svc.storage.upload("tts", path, wav, "audio/wav")
    except Exception:  # noqa: BLE001
        pass
    return Response(content=wav, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})


# ---------------------------------------------------------------------------- sources

@router.get("/sources/record/{record_id}")
def record_source(record_id: str, translate: bool = True, user: AssistUser = Depends(assist_user),
                  svc: AssistService = Depends(get_service)):
    row = svc.repo.record_source(user.tenant_id, _uuid(record_id, "record id"))
    # Only approved knowledge is visible to everyone; drafts only to their author and supervisors
    if not row or (row["status"] != "approved" and user.role != "supervisor" and str(row["author_id"]) != user.id):
        raise api_error(404, "not_found", "Source not found.")
    local = None
    if translate:
        if row.get("language") == user.language and row.get("fields_local"):
            local = row["fields_local"]
        else:
            local = svc.fields_in(f"rec:{row['id']}", dict(row.get("fields") or {}), user.language)
    return record_source_view(row, local=local, signed_url=lambda p: svc.signed("audio", p))


@router.get("/sources/manual/{document_id}")
def manual_source(document_id: str, page: int | None = Query(None, ge=1, le=2000),
                  user: AssistUser = Depends(assist_user), svc: AssistService = Depends(get_service)):
    doc = svc.repo.manual_page(user.tenant_id, _uuid(document_id, "document id"), page)
    if not doc:
        raise api_error(404, "not_found", "Source not found.")
    return manual_source_view(doc, page=page, pdf_url=svc.signed("documents", doc.get("file_path"), 1800))


@router.get("/sources/log/{log_id}")
def log_source(log_id: str, user: AssistUser = Depends(assist_user), svc: AssistService = Depends(get_service)):
    row = svc.repo.log_source(user.tenant_id, _uuid(log_id, "log id"))
    if not row:
        raise api_error(404, "not_found", "Source not found.")
    return log_source_view(row)


# ---------------------------------------------------------------------------- machines

@router.get("/machines/qr/{token}")
def machine_by_qr(token: str, user: AssistUser = Depends(assist_user), svc: AssistService = Depends(get_service)):
    if not (8 <= len(token) <= 64) or not token.isalnum():
        raise api_error(404, "machine_not_found", "This QR code isn't a Kaarigar machine sticker.")
    m = svc.repo.machine_by_qr(user.tenant_id, token)
    if not m:
        raise api_error(404, "machine_not_found", "This QR code isn't a Kaarigar machine sticker.")
    return _machine_out(m)


@router.get("/machines/{code}")
def machine_by_code(code: str, user: AssistUser = Depends(assist_user), svc: AssistService = Depends(get_service)):
    m = svc.repo.machine_by_code(user.tenant_id, code)
    if not m:
        raise api_error(404, "machine_not_found", "Machine not found.")
    return _machine_out(m)
