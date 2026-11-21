"""Escalations.

/expert/*               the expert's inbox on the phone (role expert or supervisor)
/manager/escalations*   W2 Escalations on the web (supervisor)

An expert answers in one of two ways:
  - Voice reply  -> POST /expert/escalations/{id}/reply creates a Phase 2 capture record linked to the
                    escalation. The expert checks it on "Check your note" and sends it; when it reaches
                    `pending`, 0004's trigger marks the escalation answered. After approval it is
                    normal knowledge (label E), so Kaarigar can answer the next person itself.
  - Quick text   -> POST /expert/escalations/{id}/reply-text ("Coming in 10 minutes", "Check the fuse F3").
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field

from app.capture.audio import extension_for

from .adapters import AssistUser, assist_user
from .errors import api_error
from .router_assist import AUDIO_EXT_BY_NAME
from .service import AssistService, get_service
from .views import escalation_item, escalation_view

expert_router = APIRouter(prefix="/expert", tags=["escalations"])
manager_router = APIRouter(prefix="/manager", tags=["escalations"])

CAN_ANSWER = {"expert", "supervisor"}
MAX_REPLY_AUDIO_MB = 10.0


class ReplyTextBody(BaseModel):
    text: str = Field(min_length=2, max_length=1000)


class AssignBody(BaseModel):
    user_id: str


class CloseBody(BaseModel):
    reason: Literal["not_needed", "fixed_by_technician"] = "not_needed"


def answerer(user: AssistUser = Depends(assist_user)) -> AssistUser:
    if user.role not in CAN_ANSWER:
        raise api_error(403, "not_allowed", "Only experts and supervisors can answer questions.")
    return user


def supervisor(user: AssistUser = Depends(assist_user)) -> AssistUser:
    if user.role != "supervisor":
        raise api_error(403, "not_allowed", "Only supervisors can manage escalations.")
    return user


def _signed(svc: AssistService):
    return lambda p: svc.signed("audio", p)


def _load(svc: AssistService, user: AssistUser, escalation_id: str) -> dict:
    try:
        uuid.UUID(escalation_id)
    except ValueError:
        raise api_error(422, "invalid_id", "Not a valid escalation id.")
    row = svc.repo.get_escalation(user.tenant_id, escalation_id)
    if not row:
        raise api_error(404, "not_found", "Escalation not found.")
    return row


def _visible_to_expert(row: dict, user: AssistUser) -> bool:
    if user.role == "supervisor":
        return True
    return row.get("assigned_to") is None or str(row["assigned_to"]) == user.id or str(row.get("replied_by")) == user.id


def _check_can_reply(row: dict, user: AssistUser) -> None:
    if row["status"] != "open":
        raise api_error(409, "not_open", "This question has already been answered or closed.")
    if str(row.get("asked_by")) == user.id:
        raise api_error(409, "own_question", "You can't answer your own question.")
    if row.get("assigned_to") and str(row["assigned_to"]) != user.id and user.role != "supervisor":
        raise api_error(409, "assigned_to_other", "Another expert is answering this question.")


# ============================================================================ expert (phone)

@expert_router.get("/escalations")
def inbox(scope: Literal["open", "done"] = "open", limit: int = Query(30, ge=1, le=100),
          user: AssistUser = Depends(answerer), svc: AssistService = Depends(get_service)):
    if scope == "open":
        rows = svc.repo.list_escalations(user.tenant_id, status="open", assigned_to=user.id,
                                         include_unassigned=True, limit=limit)
    else:
        rows = svc.repo.list_escalations(user.tenant_id, status="answered", assigned_to=user.id,
                                         include_unassigned=False, limit=limit)
    rows = [r for r in rows if str(r.get("asked_by")) != user.id]
    return {"items": [escalation_item(r) for r in rows]}


@expert_router.get("/escalations/count")
def inbox_count(user: AssistUser = Depends(answerer), svc: AssistService = Depends(get_service)):
    c = svc.repo.escalation_counts(user.tenant_id, user.id)
    return {"mine": c["mine"], "unassigned": c["unassigned"]}


@expert_router.get("/escalations/{escalation_id}")
def expert_get(escalation_id: str, user: AssistUser = Depends(answerer), svc: AssistService = Depends(get_service)):
    row = _load(svc, user, escalation_id)
    if not _visible_to_expert(row, user):
        raise api_error(404, "not_found", "Escalation not found.")
    return escalation_view(row, signed_url=_signed(svc))


@expert_router.post("/escalations/{escalation_id}/take")
def take(escalation_id: str, user: AssistUser = Depends(answerer), svc: AssistService = Depends(get_service)):
    row = _load(svc, user, escalation_id)
    _check_can_reply(row, user)
    if not svc.repo.assign_escalation(user.tenant_id, escalation_id, user.id):
        raise api_error(409, "not_open", "This question has already been answered or closed.")
    return escalation_view(svc.repo.get_escalation(user.tenant_id, escalation_id), signed_url=_signed(svc))


@expert_router.post("/escalations/{escalation_id}/reply", status_code=202)
async def reply_voice(
    escalation_id: str,
    audio: Annotated[UploadFile | None, File()] = None,
    transcript_en: Annotated[str | None, Form()] = None,
    user: AssistUser = Depends(answerer),
    svc: AssistService = Depends(get_service),
):
    from fastapi.concurrency import run_in_threadpool

    row = await run_in_threadpool(_load, svc, user, escalation_id)
    _check_can_reply(row, user)
    if not row.get("machine_id"):
        raise api_error(409, "no_machine", "This question has no machine; reply with a text message instead.")
    if row.get("reply_record_id") and row.get("reply_record_status") in ("draft", "expert_review"):
        raise api_error(409, "reply_in_progress", "You already have a reply waiting to be checked.")

    record_id = str(uuid.uuid4())
    audio_path = None
    if transcript_en is not None:
        if not svc.settings.is_dev:
            raise api_error(403, "text_mode_disabled", "Text notes are only allowed in development.")
        transcript_en = transcript_en.strip()
        if not (20 <= len(transcript_en) <= 6000):
            raise api_error(422, "bad_transcript", "Transcript must be 20 to 6000 characters.")
    elif audio is not None:
        ext = extension_for(audio.content_type)
        if not ext and audio.filename and "." in audio.filename:
            ext = AUDIO_EXT_BY_NAME.get(audio.filename.rsplit(".", 1)[-1].lower())
        if not ext:
            raise api_error(415, "unsupported_audio", "Send a webm, ogg, m4a, mp3, aac or wav recording.")
        limit = int(MAX_REPLY_AUDIO_MB * 1024 * 1024)
        data = await audio.read(limit + 1)
        if len(data) > limit:
            raise api_error(413, "audio_too_big", f"Recording is larger than {MAX_REPLY_AUDIO_MB:g} MB.")
        if len(data) < 1000:
            raise api_error(422, "audio_empty", "The recording is empty.")
        audio_path = f"{user.tenant_id}/{record_id}.{ext}"
        try:
            await run_in_threadpool(svc.storage.upload, "audio", audio_path, data,
                                    audio.content_type or "application/octet-stream")
        except Exception:  # noqa: BLE001
            raise api_error(502, "storage_failed", "Couldn't save the recording. Try again.")
    else:
        raise api_error(422, "audio_required", "Attach a recording.")

    if not row.get("assigned_to"):
        await run_in_threadpool(svc.repo.assign_escalation, user.tenant_id, escalation_id, user.id)
    await run_in_threadpool(lambda: svc.start_reply(
        record_id=record_id, tenant_id=user.tenant_id, machine_id=str(row["machine_id"]), author_id=user.id,
        language=user.language, audio_path=audio_path, transcript_en=transcript_en, escalation_id=escalation_id))
    return {"record_id": record_id}


@expert_router.post("/escalations/{escalation_id}/reply-text")
def reply_text(escalation_id: str, body: ReplyTextBody, user: AssistUser = Depends(answerer),
               svc: AssistService = Depends(get_service)):
    row = _load(svc, user, escalation_id)
    _check_can_reply(row, user)
    text = " ".join(body.text.split())
    if len(text) < 2:
        raise api_error(422, "bad_reply", "Write a short reply.")
    if not svc.repo.set_reply_text(user.tenant_id, escalation_id, user.id, text):
        raise api_error(409, "not_open", "This question has already been answered or closed.")
    return escalation_view(svc.repo.get_escalation(user.tenant_id, escalation_id), signed_url=_signed(svc))


# ============================================================================ manager (web, W2)

@manager_router.get("/escalations")
def manager_list(status: Literal["open", "answered", "closed", "all"] = "open",
                 limit: int = Query(50, ge=1, le=200), user: AssistUser = Depends(supervisor),
                 svc: AssistService = Depends(get_service)):
    rows = svc.repo.list_escalations(user.tenant_id, status=None if status == "all" else status, assigned_to=None,
                                     include_unassigned=False, limit=limit)
    counts = svc.repo.escalation_counts(user.tenant_id)
    return {"items": [escalation_item(r) for r in rows], "counts": {"open": counts["open"],
                                                                     "unassigned": counts["unassigned"]}}


@manager_router.get("/escalations/count")
def manager_count(user: AssistUser = Depends(supervisor), svc: AssistService = Depends(get_service)):
    c = svc.repo.escalation_counts(user.tenant_id)
    return {"open": c["open"], "unassigned": c["unassigned"]}


@manager_router.get("/experts")
def experts(user: AssistUser = Depends(supervisor), svc: AssistService = Depends(get_service)):
    return {"items": [{"id": str(r["id"]), "name": r["name"], "role": r["role"], "language": r.get("language"),
                       "open_assigned": int(r.get("open_assigned") or 0),
                       "approved_records": int(r.get("approved_records") or 0)} for r in svc.repo.experts(user.tenant_id)]}


@manager_router.get("/escalations/{escalation_id}")
def manager_get(escalation_id: str, user: AssistUser = Depends(supervisor), svc: AssistService = Depends(get_service)):
    return escalation_view(_load(svc, user, escalation_id), signed_url=_signed(svc))


@manager_router.post("/escalations/{escalation_id}/assign")
def assign(escalation_id: str, body: AssignBody, user: AssistUser = Depends(supervisor),
           svc: AssistService = Depends(get_service)):
    row = _load(svc, user, escalation_id)
    if row["status"] != "open":
        raise api_error(409, "not_open", "Only open questions can be assigned.")
    try:
        target_id = str(uuid.UUID(body.user_id))
    except ValueError:
        raise api_error(422, "invalid_id", "Not a valid user id.")
    target = svc.repo.user_in_tenant(user.tenant_id, target_id)
    if not target or target["role"] not in CAN_ANSWER:
        raise api_error(422, "not_an_expert", "Pick an expert or a supervisor.")
    if str(row.get("asked_by")) == target_id:
        raise api_error(422, "own_question", "The person who asked can't answer their own question.")
    if not svc.repo.assign_escalation(user.tenant_id, escalation_id, target_id):
        raise api_error(409, "not_open", "Only open questions can be assigned.")
    return escalation_view(svc.repo.get_escalation(user.tenant_id, escalation_id), signed_url=_signed(svc))


@manager_router.post("/escalations/{escalation_id}/close")
def close(escalation_id: str, body: CloseBody, user: AssistUser = Depends(supervisor),
          svc: AssistService = Depends(get_service)):
    row = _load(svc, user, escalation_id)
    if row["status"] == "closed":
        raise api_error(409, "already_closed", "This question is already closed.")
    svc.repo.close_escalation(user.tenant_id, escalation_id, body.reason)
    return escalation_view(svc.repo.get_escalation(user.tenant_id, escalation_id), signed_url=_signed(svc))
