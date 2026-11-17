"""Job helpers + the one-at-a-time ingestion lock.

Jobs run via FastAPI BackgroundTasks (sync functions → thread pool).
A module-level Semaphore(1) keeps ingestion RAM low on a 1-2 GB server.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable

from app.core.db import db

logger = logging.getLogger("kaarigar.jobs")

# One ingestion job at a time (PDF embed + Excel import share the same budget).
ingest_lock = threading.Semaphore(1)


def create_job(tenant_id: str, type: str, ref_id: str | None) -> str:
    job_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            "insert into jobs (id, tenant_id, type, ref_id) values (%s, %s, %s, %s)",
            (job_id, tenant_id, type, ref_id),
        )
    return job_id


def update(job_id: str, progress: int | None = None, status: str | None = None, error: str | None = None) -> None:
    sets = ["updated_at = now()"]
    params: list = []
    if progress is not None:
        sets.append("progress = %s")
        params.append(progress)
    if status is not None:
        sets.append("status = %s")
        params.append(status)
    if error is not None:
        sets.append("error = %s")
        params.append(error)
    params.append(job_id)
    with db() as conn:
        conn.execute(f"update jobs set {', '.join(sets)} where id = %s", params)


def fail_stale_jobs() -> None:
    """On startup: jobs still queued/running died with the previous process."""
    with db() as conn:
        cur = conn.execute(
            "update jobs set status = 'failed', error = 'server restarted', updated_at = now() "
            "where status in ('queued', 'running')"
        )
        if cur.rowcount:
            logger.info("marked %s stale job(s) as failed", cur.rowcount)


def run_job(job_id: str, fn: Callable[[], None]) -> None:
    """Wrap a job body: acquires the ingest lock, updates status/progress, never raises."""
    update(job_id, status="running")
    try:
        with ingest_lock:
            fn()
    except Exception as e:
        logger.exception("job %s failed", job_id)
        update(job_id, status="failed", error=str(e)[:500])
    else:
        # fn() is responsible for its own final progress/status; ensure done if it didn't
        from app.core.db import db as _db

        with _db() as conn:
            row = conn.execute("select status from jobs where id = %s", (job_id,)).fetchone()
        if row and row[0] in ("queued", "running"):
            update(job_id, status="done", progress=100)
