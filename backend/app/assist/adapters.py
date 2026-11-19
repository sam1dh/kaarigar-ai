"""THE ONLY FILE IN app/assist THAT TOUCHES EARLIER PHASES.

Phase 3 reuses Phase 2's adapters (current user, db connection, storage), so the ADAPT work
you did in app/capture/adapters.py applies here too. The only new ADAPT point is the
Phase 1 search call in `hybrid_search()`.

What Phase 3 needs:
  1. current user, db, storage        -> re-exported from app.capture.adapters
  2. Phase 1 hybrid search             -> hybrid_search()          (ADAPT if the signature differs)
  3. Phase 2 capture pipeline          -> start_reply_capture()    (an expert's voice reply becomes a record)
"""
from __future__ import annotations

import logging
from typing import Any

from app.capture.adapters import (  # noqa: F401  re-exported on purpose
    CaptureUser as AssistUser,
    capture_user as assist_user,
    db_conn,
    storage_delete,
    storage_download,
    storage_signed_url,
    storage_upload,
)

from .errors import AssistError

log = logging.getLogger("kaarigar.assist.adapters")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# 2. Phase 1 hybrid search  (ADAPT: function path / signature / result shape)

def hybrid_search(tenant_id: str, q: str, machine_code: str | None, k: int) -> dict:
    """Returns {"results": [...], "confidence": float|None, "expanded_query": str}.

    Each result is normalised to: label, source_type, source_id, chunk_id, title, section, page,
    text, score, same_machine, meta. Raises AssistError("search_failed") if search breaks.
    """
    try:
        from app.services.search import search  # ADAPT if Phase 1 put it elsewhere

        res = search(tenant_id=tenant_id, q=q[:300], machine_code=machine_code, k=k)
    except AssistError:
        raise
    except Exception as e:  # noqa: BLE001  (includes Phase 1's 404 for an unknown machine)
        log.warning("search failed: %s", type(e).__name__)
        raise AssistError("search_failed") from e

    raw = _get(res, "results", []) or []
    results = []
    for r in raw:
        results.append({
            "label": _get(r, "label") or {"record": "E", "manual": "M", "log": "H"}.get(_get(r, "source_type"), "M"),
            "source_type": _get(r, "source_type"),
            "source_id": str(_get(r, "source_id")),
            "chunk_id": str(_get(r, "chunk_id")) if _get(r, "chunk_id") else None,
            "title": _get(r, "title") or "",
            "section": _get(r, "section"),
            "page": _get(r, "page"),
            "text": _get(r, "text") or "",
            "score": float(_get(r, "score") or 0.0),
            "same_machine": bool(_get(r, "same_machine", False)),
            "meta": dict(_get(r, "meta") or {}),
        })
    conf = _get(res, "confidence")
    return {"results": results, "confidence": float(conf) if conf is not None else None,
            "expanded_query": _get(res, "expanded_query") or q}


# ---------------------------------------------------------------------------
# 3. Phase 2 capture: an expert's voice reply to an escalation becomes a normal repair record.
#    The expert then checks it on Phase 2's "Check your note" screen and sends it to the supervisor.
#    0004's trigger marks the escalation answered when the record reaches `pending`.

def start_reply_capture(*, record_id: str, tenant_id: str, machine_id: str, author_id: str, language: str,
                        audio_path: str | None, transcript_en: str | None, escalation_id: str) -> None:
    from app.capture.repo import PostgresRepo
    from app.capture.runner import get_runner

    from .repo import PostgresAssistRepo

    PostgresRepo(db_conn).create_record(record_id=record_id, tenant_id=tenant_id, machine_id=machine_id,
                                        author_id=author_id, language=language, audio_path=audio_path,
                                        transcript_en=transcript_en)
    PostgresAssistRepo(db_conn).link_reply_record(tenant_id, record_id, escalation_id)
    get_runner().start(record_id, tenant_id)
