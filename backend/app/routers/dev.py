"""Dev-only endpoints: /dev/search and /dev/stats (mounted only in development)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.auth import CurrentUser, require_role
from app.core.config import get_settings
from app.core.db import db
from app.services import embeddings
from app.services import search as search_svc

router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/search")
def dev_search(
    q: str = Query(..., min_length=2, max_length=300),
    machine: str | None = Query(None),
    k: int = Query(8, ge=1, le=20),
    rerank: bool | None = Query(None),
    debug: bool = Query(False),
    user: CurrentUser = Depends(require_role("supervisor")),
) -> dict:
    return search_svc.search(
        user.tenant_id,
        q,
        machine_code=machine,
        k=k,
        rerank=rerank,
        debug=debug,
    )


@router.get("/stats")
def dev_stats(user: CurrentUser = Depends(require_role("supervisor"))) -> dict:
    with db() as conn:
        chunk_rows = conn.execute(
            """select source_type, count(*) from chunks
               where tenant_id = %s group by source_type""",
            (user.tenant_id,),
        ).fetchall()
        docs = conn.execute(
            "select count(*) from documents where tenant_id = %s", (user.tenant_id,)
        ).fetchone()[0]
        logs = conn.execute(
            "select count(*) from maintenance_logs where tenant_id = %s", (user.tenant_id,)
        ).fetchone()[0]
        records = conn.execute(
            "select count(*) from repair_records where tenant_id = %s", (user.tenant_id,)
        ).fetchone()[0]
    chunks = {r[0]: r[1] for r in chunk_rows}
    return {
        "chunks": {
            "manual": chunks.get("manual", 0),
            "record": chunks.get("record", 0),
            "log": chunks.get("log", 0),
        },
        "documents": docs,
        "logs": logs,
        "records": records,
        "embed_model": get_settings().embed_model,
        "rerank": embeddings.status()["rerank"],
    }
