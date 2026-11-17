"""/manager/* review queue — the supervisor's side (web). Any supervisor can review (admin not required)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from . import adapters
from .adapters import CaptureUser, capture_user
from .errors import CaptureError, api_error
from .router_capture import get_repo
from .runner import CaptureRunner, NotWaiting, get_runner
from .schemas import ApproveBody, RejectBody
from .views import queue_item, record_view

router = APIRouter(prefix="/manager", tags=["review"])


def supervisor(user: CaptureUser = Depends(capture_user)) -> CaptureUser:
    if user.role != "supervisor":
        raise api_error(403, "not_allowed", "Only supervisors can review records.")
    return user


def _signed(path: str) -> str | None:
    return adapters.storage_signed_url("audio", path, 3600)


def _load(repo, user: CaptureUser, record_id: str) -> dict:
    try:
        uuid.UUID(record_id)
    except ValueError:
        raise api_error(422, "invalid_id", "Not a valid record id.")
    rec = repo.get(user.tenant_id, record_id)
    if not rec:
        raise api_error(404, "not_found", "Record not found.")
    return rec


@router.get("/review-queue")
def review_queue(limit: int = Query(50, ge=1, le=100), user: CaptureUser = Depends(supervisor),
                 repo=Depends(get_repo)):
    rows = repo.review_queue(user.tenant_id, limit)
    return {"items": [queue_item(r) for r in rows], "count": repo.pending_count(user.tenant_id)}


@router.get("/review-queue/count")
def review_count(user: CaptureUser = Depends(supervisor), repo=Depends(get_repo)):
    return {"count": repo.pending_count(user.tenant_id)}


@router.get("/records/{record_id}")
def get_record(record_id: str, user: CaptureUser = Depends(supervisor), repo=Depends(get_repo)):
    return record_view(_load(repo, user, record_id), viewer_id=user.id, viewer_role=user.role, signed_url=_signed)


def _check_reviewable(rec: dict, user: CaptureUser) -> None:
    if rec["status"] != "pending":
        raise api_error(409, "not_pending", "This record has already been reviewed.")
    if str(rec["author_id"]) == user.id:
        raise api_error(409, "own_record", "You can't review your own record.")


@router.post("/records/{record_id}/approve")
def approve(record_id: str, body: ApproveBody, user: CaptureUser = Depends(supervisor), repo=Depends(get_repo),
            runner: CaptureRunner = Depends(get_runner)):
    rec = _load(repo, user, record_id)
    _check_reviewable(rec, user)
    edits = body.edits.model_dump(exclude_unset=True)
    merged = {**(rec.get("fields") or {}), **edits}
    if not merged.get("symptom") or not merged.get("fix"):
        raise api_error(422, "incomplete", "A record needs at least the problem and the fix before approval.")
    try:
        runner.review(record_id, {"action": "approve", "edits": edits, "reviewer_id": user.id})
    except NotWaiting:
        raise api_error(409, "not_pending", "This record has already been reviewed.")
    except CaptureError as e:
        raise api_error(503, e.code, e.user_message)
    return record_view(repo.get(user.tenant_id, record_id), viewer_id=user.id, viewer_role=user.role,
                       signed_url=_signed)


@router.post("/records/{record_id}/reject")
def reject(record_id: str, body: RejectBody, user: CaptureUser = Depends(supervisor), repo=Depends(get_repo),
           runner: CaptureRunner = Depends(get_runner)):
    rec = _load(repo, user, record_id)
    _check_reviewable(rec, user)
    try:
        runner.review(record_id, {"action": "reject", "reason": body.reason.strip(), "reviewer_id": user.id})
    except NotWaiting:
        raise api_error(409, "not_pending", "This record has already been reviewed.")
    return record_view(repo.get(user.tenant_id, record_id), viewer_id=user.id, viewer_role=user.role,
                       signed_url=_signed)
