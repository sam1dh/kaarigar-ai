"""/capture/* — the expert's side (phone)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status

from . import adapters
from .adapters import CaptureUser, capture_user
from .audio import extension_for
from .errors import CaptureError, api_error
from .repo import PostgresRepo
from .runner import CaptureRunner, NotWaiting, get_runner
from .schemas import SubmitBody
from .settings import CaptureSettings, get_capture_settings
from .views import record_view

router = APIRouter(prefix="/capture", tags=["capture"])
CAN_CAPTURE = {"expert", "supervisor"}


def get_repo() -> PostgresRepo:
    return PostgresRepo(adapters.db_conn)


def _signed(path: str) -> str | None:
    return adapters.storage_signed_url("audio", path, 3600)


def _load_own(repo, user: CaptureUser, record_id: str) -> dict:
    try:
        uuid.UUID(record_id)
    except ValueError:
        raise api_error(422, "invalid_id", "Not a valid record id.")
    rec = repo.get(user.tenant_id, record_id)
    # Same 404 for "doesn't exist", "other plant" and "not yours": reveal nothing
    if not rec or (str(rec["author_id"]) != user.id and user.role != "supervisor"):
        raise api_error(404, "not_found", "Record not found.")
    return rec


@router.post("/records", status_code=status.HTTP_202_ACCEPTED)
async def create_record(
    machine_code: Annotated[str, Form(min_length=1, max_length=40)],
    audio: Annotated[UploadFile | None, File()] = None,
    transcript_en: Annotated[str | None, Form()] = None,
    user: CaptureUser = Depends(capture_user),
    repo=Depends(get_repo),
    runner: CaptureRunner = Depends(get_runner),
    s: CaptureSettings = Depends(get_capture_settings),
):
    if user.role not in CAN_CAPTURE:
        raise api_error(403, "not_allowed", "Only experts and supervisors can record repairs.")
    machine = repo.machine_by_code(user.tenant_id, machine_code)
    if not machine:
        raise api_error(404, "machine_not_found", "Machine not found.")

    record_id = str(uuid.uuid4())
    audio_path = None
    if transcript_en is not None:
        if not s.is_dev:
            raise api_error(403, "text_mode_disabled", "Text notes are only allowed in development.")
        transcript_en = transcript_en.strip()
        if not (20 <= len(transcript_en) <= 6000):
            raise api_error(422, "bad_transcript", "Transcript must be 20 to 6000 characters.")
    elif audio is not None:
        ext = extension_for(audio.content_type)
        if not ext and audio.filename and "." in audio.filename:
            ext = {"webm": "webm", "ogg": "ogg", "m4a": "m4a", "mp4": "m4a", "mp3": "mp3", "wav": "wav",
                   "aac": "aac"}.get(audio.filename.rsplit(".", 1)[-1].lower())
        if not ext:
            raise api_error(415, "unsupported_audio", "Send a webm, ogg, m4a, mp3, aac or wav recording.")
        limit = int(s.MAX_AUDIO_MB * 1024 * 1024)
        data = await audio.read(limit + 1)
        if len(data) > limit:
            raise api_error(413, "audio_too_big", f"Recording is larger than {s.MAX_AUDIO_MB:g} MB.")
        if len(data) < 1000:
            raise api_error(422, "audio_empty", "The recording is empty.")
        audio_path = f"{user.tenant_id}/{record_id}.{ext}"   # never built from the user's file name
        try:
            adapters.storage_upload("audio", audio_path, data, audio.content_type or "application/octet-stream")
        except Exception:  # noqa: BLE001
            raise api_error(502, "storage_failed", "Couldn't save the recording. Try again.")
    else:
        raise api_error(422, "audio_required", "Attach a recording.")

    repo.create_record(record_id=record_id, tenant_id=user.tenant_id, machine_id=str(machine["id"]),
                       author_id=user.id, language=user.language, audio_path=audio_path,
                       transcript_en=transcript_en)
    runner.start(record_id, user.tenant_id)
    return {"record_id": record_id}


@router.get("/records")
def list_my_records(
    machine_code: str | None = None,
    limit: int = Query(20, ge=1, le=50),
    user: CaptureUser = Depends(capture_user),
    repo=Depends(get_repo),
):
    machine_id = None
    if machine_code:
        m = repo.machine_by_code(user.tenant_id, machine_code)
        if not m:
            raise api_error(404, "machine_not_found", "Machine not found.")
        machine_id = str(m["id"])
    rows = repo.list_by_author(user.tenant_id, user.id, machine_id, limit)
    return {"items": [record_view(r, viewer_id=user.id, viewer_role=user.role, include_audio=False) for r in rows]}


@router.get("/records/{record_id}")
def get_record(record_id: str, user: CaptureUser = Depends(capture_user), repo=Depends(get_repo)):
    rec = _load_own(repo, user, record_id)
    return record_view(rec, viewer_id=user.id, viewer_role=user.role, signed_url=_signed)


@router.post("/records/{record_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_record(record_id: str, user: CaptureUser = Depends(capture_user), repo=Depends(get_repo),
                 runner: CaptureRunner = Depends(get_runner)):
    rec = _load_own(repo, user, record_id)
    view = record_view(rec, viewer_id=user.id, viewer_role=user.role)
    if not view["can"]["retry"]:
        if view["error"] and not view["error"]["retryable"]:
            raise api_error(409, "record_again", "This note can't be fixed by retrying. Please record again.")
        raise api_error(409, "not_failed", "This note isn't in a failed state.")
    runner.retry(record_id, user.tenant_id)
    return {"record_id": record_id}


@router.post("/records/{record_id}/submit")
def submit_record(record_id: str, body: SubmitBody, user: CaptureUser = Depends(capture_user),
                  repo=Depends(get_repo), runner: CaptureRunner = Depends(get_runner)):
    rec = _load_own(repo, user, record_id)
    if str(rec["author_id"]) != user.id:
        raise api_error(403, "not_author", "Only the person who recorded this note can send it.")
    if not (rec["status"] == "expert_review" and rec.get("stage") == "ready"):
        raise api_error(409, "not_editable", "This note can't be sent right now.")
    edits = body.edits.model_dump(exclude_unset=True)
    decision = {"action": "submit", "edits": edits, "edit_language": body.edit_language}
    try:
        runner.submit_expert(record_id, decision)
    except NotWaiting:
        raise api_error(409, "not_editable", "This note can't be sent right now.")
    except CaptureError as e:
        raise api_error(503, e.code, e.user_message)
    return record_view(repo.get(user.tenant_id, record_id), viewer_id=user.id, viewer_role=user.role,
                       signed_url=_signed)


@router.delete("/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard_record(record_id: str, user: CaptureUser = Depends(capture_user), repo=Depends(get_repo),
                   runner: CaptureRunner = Depends(get_runner)):
    rec = _load_own(repo, user, record_id)
    if str(rec["author_id"]) != user.id:
        raise api_error(403, "not_author", "Only the person who recorded this note can delete it.")
    if rec["status"] not in ("draft", "expert_review"):
        raise api_error(409, "not_deletable", "Notes sent to the supervisor can't be deleted.")
    if rec.get("stage") in ("queued", "transcribing", "extracting", "checking", "translating"):
        raise api_error(409, "still_processing", "Wait until the note has been processed.")
    runner.discard(record_id, user.tenant_id)
    return Response(status_code=204)
