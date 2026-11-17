"""THE ONLY FILE THAT TOUCHES PHASE 0 / PHASE 1 CODE.

Every import from the existing app lives here. If a name below doesn't match your code,
fix it HERE (look for "ADAPT") and nothing else in app/capture needs to change.

What Phase 2 needs from earlier phases:
  1. current user (Phase 0 auth)          -> capture_user()
  2. a psycopg connection (Phase 1 db)    -> db_conn()
  3. Supabase Storage, service role       -> storage_upload / storage_download / storage_delete / storage_signed_url
  4. hybrid search (Phase 1)              -> manual_excerpts()
  5. record -> search chunk (Phase 1)     -> rebuild_record_chunks()
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from fastapi import Depends

log = logging.getLogger("kaarigar.capture.adapters")

# ---------------------------------------------------------------------------
# 1. Current user  (ADAPT: Phase 0 dependency name / return shape)

from app.core.auth import get_current_user  # noqa: E402  ADAPT if your dependency has another name


@dataclass(frozen=True)
class CaptureUser:
    id: str
    tenant_id: str
    role: str            # technician | expert | supervisor
    is_admin: bool
    language: str
    name: str


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def to_capture_user(u: Any) -> CaptureUser:
    tenant = _get(u, "tenant")
    tenant_id = _get(u, "tenant_id") or _get(tenant, "id")
    if not tenant_id:
        raise RuntimeError("ADAPT: current user has no tenant_id (or tenant.id)")
    return CaptureUser(
        id=str(_get(u, "id") or _get(u, "user_id")),
        tenant_id=str(tenant_id),
        role=str(_get(u, "role", "technician")),
        is_admin=bool(_get(u, "is_admin", False)),
        language=str(_get(u, "language") or "en-IN"),
        name=str(_get(u, "name") or ""),
    )


def capture_user(u: Any = Depends(get_current_user)) -> CaptureUser:
    return to_capture_user(u)


# ---------------------------------------------------------------------------
# 2. Database connection  (ADAPT: Phase 1 helper in app/core/db.py)

@contextmanager
def db_conn() -> Iterator[Any]:
    """Yields a psycopg 3 connection. Repo code calls conn.commit() itself after writes."""
    from app.core.db import db  # ADAPT if the Phase 1 helper has another name

    with db() as conn:
        yield conn


# ---------------------------------------------------------------------------
# 3. Supabase Storage with the service-role client  (ADAPT: client name in app/core/supabase.py)

def _service_client() -> Any:
    import app.core.supabase as s  # ADAPT module path if different

    for name in ("service_client", "admin_client", "supabase_admin", "service",
                 "get_service_client", "get_admin_client", "get_service_role_client"):
        obj = getattr(s, name, None)
        if obj is None:
            continue
        if hasattr(obj, "storage"):
            return obj
        if callable(obj):
            client = obj()
            if hasattr(client, "storage"):
                return client
    raise RuntimeError("ADAPT: point _service_client() at the service-role Supabase client")


def storage_upload(bucket: str, path: str, data: bytes, content_type: str) -> None:
    _service_client().storage.from_(bucket).upload(
        path, data, {"content-type": content_type, "upsert": "true"}
    )


def storage_download(bucket: str, path: str) -> bytes:
    return _service_client().storage.from_(bucket).download(path)


def storage_delete(bucket: str, path: str) -> None:
    try:
        _service_client().storage.from_(bucket).remove([path])
    except Exception as e:  # noqa: BLE001  deleting a missing file is not an error for us
        log.info("storage delete ignored: %s", type(e).__name__)


def storage_signed_url(bucket: str, path: str, expires_sec: int = 3600) -> str | None:
    try:
        res = _service_client().storage.from_(bucket).create_signed_url(path, expires_sec)
    except Exception as e:  # noqa: BLE001
        log.info("signed url failed: %s", type(e).__name__)
        return None
    if isinstance(res, dict):
        return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
    return getattr(res, "signed_url", None) or getattr(res, "signedURL", None)


# ---------------------------------------------------------------------------
# 4. Phase 1 search: manual excerpts for the AI check  (ADAPT: search() signature)

def manual_excerpts(tenant_id: str, query: str, machine_code: str | None, k: int = 3) -> list[dict]:
    """Up to k manual (M) chunks for this machine's model. Never raises: the AI check works without them."""
    if not query:
        return []
    try:
        from app.services.search import search  # ADAPT

        res = search(tenant_id=tenant_id, q=query[:300], machine_code=machine_code, k=8)
        results = res.get("results", []) if isinstance(res, dict) else _get(res, "results", [])
        out = []
        for r in results:
            if _get(r, "label") == "M" or _get(r, "source_type") == "manual":
                out.append({"title": _get(r, "title", "Manual"), "text": _get(r, "text", "")})
            if len(out) >= k:
                break
        return out
    except Exception as e:  # noqa: BLE001
        log.info("manual excerpts unavailable: %s", type(e).__name__)
        return []


# ---------------------------------------------------------------------------
# 5. Phase 1 chunks  (ADAPT: function location/name)

def rebuild_record_chunks(record_id: str) -> None:
    """Approved -> one search chunk; any other status -> chunk removed."""
    from app.services.knowledge import rebuild_record_chunks as _rebuild  # ADAPT

    _rebuild(record_id)
