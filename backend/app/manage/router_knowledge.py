"""/manager/knowledge — W6 Knowledge base. Any supervisor.

One list of everything Kaarigar answers from: approved expert repairs (E), manuals (M), breakdown history (H),
with how often each was cited in an answer. Archiving an outdated repair takes it out of answers at once;
restoring puts it back (Phase 1 rebuilds its search chunk).
Details open with Phase 3's /assist/sources/* endpoints.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.capture.errors import api_error

from .adapters import ManageUser
from .deps import get_rebuild, get_repo, supervisor
from .views import document_item, log_item, record_item

router = APIRouter(prefix="/manager/knowledge", tags=["knowledge"])


@router.get("/stats")
def stats(user: ManageUser = Depends(supervisor), repo=Depends(get_repo)):
    s = repo.knowledge_stats(user.tenant_id)
    s["answered_rate_30d"] = round(s["answered_30d"] / s["questions_30d"], 3) if s["questions_30d"] else None
    return s


@router.get("/items")
def items(kind: Literal["all", "E", "M", "H"] = "all", machine: str | None = Query(None, max_length=20),
          q: str | None = Query(None, max_length=100), archived: bool = False,
          sort: Literal["recent", "used"] = "recent", limit: int = Query(60, ge=1, le=200),
          user: ManageUser = Depends(supervisor), repo=Depends(get_repo)):
    q = " ".join(q.split()) if q else None
    machine = machine.strip() if machine and machine.strip() else None
    out: list[dict] = []
    if kind in ("all", "E"):
        out += [record_item(r) for r in repo.knowledge_records(user.tenant_id, machine=machine, q=q,
                                                               archived=archived, limit=limit)]
    if not archived:
        if kind in ("all", "M"):
            out += [document_item(r) for r in repo.knowledge_documents(user.tenant_id, machine=machine, q=q,
                                                                       limit=limit)]
        if kind in ("all", "H"):
            out += [log_item(r) for r in repo.knowledge_logs(user.tenant_id, machine=machine, q=q, limit=limit)]
    if sort == "used":
        out.sort(key=lambda i: (i["used"], i["date"] or ""), reverse=True)
    else:
        out.sort(key=lambda i: i["date"] or "", reverse=True)
    return {"items": out[:limit], "count": len(out[:limit])}


def _record(repo, user: ManageUser, record_id: str) -> dict:
    try:
        rid = str(uuid.UUID(record_id))
    except ValueError:
        raise api_error(422, "invalid_id", "Not a valid record id.")
    row = repo.get_record(user.tenant_id, rid)
    if not row:
        raise api_error(404, "not_found", "Record not found.")
    return row


@router.post("/records/{record_id}/archive")
def archive(record_id: str, user: ManageUser = Depends(supervisor), repo=Depends(get_repo)):
    row = _record(repo, user, record_id)
    if row["status"] != "approved":
        raise api_error(409, "not_approved", "Only approved repairs are in the knowledge base.")
    if row.get("archived_at"):
        raise api_error(409, "already_archived", "Already archived.")
    repo.archive_record(user.tenant_id, str(row["id"]), user.id)
    repo.audit(user.tenant_id, user.id, "record_archived", "repair_record", str(row["id"]), {})
    return {"id": str(row["id"]), "status": "archived"}


@router.post("/records/{record_id}/restore")
def restore(record_id: str, user: ManageUser = Depends(supervisor), repo=Depends(get_repo), rebuild=Depends(get_rebuild)):
    row = _record(repo, user, record_id)
    if not row.get("archived_at"):
        raise api_error(409, "not_archived", "This repair is not archived.")
    repo.unarchive_record(user.tenant_id, str(row["id"]))
    repo.audit(user.tenant_id, user.id, "record_restored", "repair_record", str(row["id"]), {})
    try:
        rebuild(str(row["id"]))
    except Exception:  # noqa: BLE001  restored, but search needs a reindex
        return {"id": str(row["id"]), "status": "ready", "warning": "search_not_updated"}
    return {"id": str(row["id"]), "status": "ready"}
