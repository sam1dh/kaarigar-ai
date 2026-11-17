"""Admin endpoints (supervisors with is_admin = true)."""

import hashlib
import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response

from app.core.auth import CurrentUser, require_admin
from app.core.db import db
from app.core.errors import ApiError
from app.services import embeddings, jobs, log_import, pdf_ingest, storage

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ping")
def ping(_: CurrentUser = Depends(require_admin)) -> dict:
    return {"ok": True, "area": "admin"}


# ===== machine models (upload form) =====

@router.get("/machine-models")
def machine_models(_: CurrentUser = Depends(require_admin)) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """select mm.id, mm.model, mm.type, mm.oem,
                      coalesce(array_agg(m.code order by m.code) filter (where m.code is not null), '{}') as codes
               from machine_models mm left join machines m on m.model_id = mm.id
               where mm.tenant_id = %s
               group by mm.id order by mm.model""",
            (_.tenant_id,),
        ).fetchall()
    return [
        {"id": str(r[0]), "model": r[1], "type": r[2], "oem": r[3], "machines": list(r[4])}
        for r in rows
    ]


# ===== documents (manual PDFs) =====

_ALLOWED_TYPES = ("manual", "sop", "safety")


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@router.post("/documents", status_code=202)
def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(...),
    type: str = Form("manual"),
    model_id: str = Form(...),
    replace: bool = Query(False),
    user: CurrentUser = Depends(require_admin),
) -> dict:
    if type not in _ALLOWED_TYPES:
        raise ApiError(422, "validation_error", "type must be manual, sop or safety.")
    if not (file.filename or "").lower().endswith(".pdf"):
        raise ApiError(422, "validation_error", "Upload a .pdf file.")
    data = file.file.read()
    fhash = _file_hash(data)

    with db() as conn:
        model = conn.execute(
            "select id from machine_models where id = %s and tenant_id = %s",
            (model_id, user.tenant_id),
        ).fetchone()
        if not model:
            raise ApiError(404, "not_found", "Unknown machine model for this plant.")
        dup = conn.execute(
            "select id, status, title from documents where tenant_id = %s and model_id = %s and file_hash = %s limit 1",
            (user.tenant_id, model_id, fhash),
        ).fetchone()
        if dup and not replace:
            raise ApiError(409, "already_uploaded", "This exact file was already uploaded for this model.")

    import uuid as _uuid

    document_id = str(_uuid.uuid4())
    path = f"documents/{user.tenant_id}/{document_id}.pdf"
    storage.upload(path, data, "application/pdf")
    with db() as conn:
        conn.execute(
            """insert into documents (id, tenant_id, model_id, title, type, file_path, status, file_hash, created_by)
               values (%s, %s, %s, %s, %s, %s, 'uploaded', %s, %s)""",
            (document_id, user.tenant_id, model_id, title.strip(), type, path, fhash, user.id),
        )
        if replace and dup:
            conn.execute("delete from chunks where source_type = 'manual' and source_id = %s", (dup[0],))
            conn.execute("delete from documents where id = %s", (dup[0],))

    job_id = jobs.create_job(user.tenant_id, "ingest_pdf", document_id)
    background.add_task(jobs.run_job, job_id, lambda: pdf_ingest.ingest_document(document_id, job_id))
    return {"document_id": document_id, "job_id": job_id}


@router.get("/documents")
def list_documents(_: CurrentUser = Depends(require_admin)) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """select d.id, d.title, d.type, mm.model, d.status, d.pages, d.quality_notes, d.error, d.created_at,
                      (select count(*) from chunks c where c.source_type = 'manual' and c.source_id = d.id)
               from documents d left join machine_models mm on mm.id = d.model_id
               where d.tenant_id = %s order by d.created_at desc""",
            (_.tenant_id,),
        ).fetchall()
    return [
        {
            "id": str(r[0]), "title": r[1], "type": r[2], "model": r[3], "status": r[4],
            "pages": r[5], "quality_notes": r[6], "error": r[7], "created_at": r[8].isoformat(),
            "chunks": r[9],
        }
        for r in rows
    ]


@router.get("/documents/{document_id}")
def get_document(document_id: str, _: CurrentUser = Depends(require_admin)) -> dict:
    with db() as conn:
        row = conn.execute(
            """select d.id, d.title, d.type, mm.model, d.status, d.pages, d.quality_notes, d.error, d.created_at
               from documents d left join machine_models mm on mm.id = d.model_id
               where d.id = %s and d.tenant_id = %s""",
            (document_id, _.tenant_id),
        ).fetchone()
        if not row:
            raise ApiError(404, "not_found", "Document not found.")
        count = conn.execute(
            "select count(*) from chunks where source_type = 'manual' and source_id = %s",
            (document_id,),
        ).fetchone()[0]
        previews = conn.execute(
            "select text from chunks where source_type = 'manual' and source_id = %s order by chunk_index limit 3",
            (document_id,),
        ).fetchall()
    return {
        "id": str(row[0]), "title": row[1], "type": row[2], "model": row[3], "status": row[4],
        "pages": row[5], "quality_notes": row[6], "error": row[7], "created_at": row[8].isoformat(),
        "chunks": count,
        "previews": [p[0][:160] for p in previews],
    }


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, _: CurrentUser = Depends(require_admin)) -> Response:
    with db() as conn:
        row = conn.execute(
            "select file_path from documents where id = %s and tenant_id = %s",
            (document_id, _.tenant_id),
        ).fetchone()
        if not row:
            raise ApiError(404, "not_found", "Document not found.")
        conn.execute("delete from chunks where source_type = 'manual' and source_id = %s", (document_id,))
        conn.execute("delete from documents where id = %s", (document_id,))
    storage.delete(row[0])
    return Response(status_code=204)


# ===== log imports (breakdown Excel/CSV) =====

@router.post("/log-imports", status_code=201)
def upload_log_import(
    file: UploadFile = File(...),
    force: bool = Query(False),
    user: CurrentUser = Depends(require_admin),
) -> dict:
    name = file.filename or "upload.xlsx"
    if not name.lower().endswith((".xlsx", ".csv")):
        raise ApiError(422, "validation_error", "Upload an .xlsx or .csv file.")
    data = file.file.read()
    fhash = hashlib.sha256(data).hexdigest()

    with db() as conn:
        dup = conn.execute(
            "select id from log_imports where tenant_id = %s and file_hash = %s and status = 'done' limit 1",
            (user.tenant_id, fhash),
        ).fetchone()
    if dup and not force:
        raise ApiError(409, "already_imported", "This exact file was already imported.")

    try:
        parsed = log_import.analyse(user.tenant_id, name, data)
    except ValueError as e:
        raise ApiError(422, "validation_error", str(e)) from None

    import uuid as _uuid

    import_id = str(_uuid.uuid4())
    path = f"imports/{user.tenant_id}/{import_id}.{'xlsx' if name.lower().endswith('.xlsx') else 'csv'}"
    storage.upload(
        path, data,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if name.lower().endswith(".xlsx") else "text/csv",
    )
    detected = {
        "header_row": parsed["header_row"],
        "columns": parsed["columns"],
        "sample_rows": parsed["sample_rows"],
        "total_rows": parsed["total_rows"],
        "mapping_source": parsed["mapping_source"],
    }
    with db() as conn:
        conn.execute(
            """insert into log_imports
               (id, tenant_id, file_path, column_mapping, status, file_name, file_hash, detected, created_by)
               values (%s, %s, %s, %s::jsonb, 'mapping', %s, %s, %s::jsonb, %s)""",
            (
                import_id, user.tenant_id, path,
                json.dumps(parsed["suggested_mapping"]),
                name, fhash, json.dumps(detected), user.id,
            ),
        )
    return {
        "import_id": import_id,
        "header_row": parsed["header_row"],
        "columns": parsed["columns"],
        "sample_rows": parsed["sample_rows"],
        "total_rows": parsed["total_rows"],
        "suggested_mapping": parsed["suggested_mapping"],
        "mapping_source": parsed["mapping_source"],
    }


@router.post("/log-imports/{import_id}/confirm", status_code=202)
def confirm_log_import(
    import_id: str,
    body: dict,
    background: BackgroundTasks,
    force: bool = Query(False),
    user: CurrentUser = Depends(require_admin),
) -> dict:
    mapping = body.get("mapping")
    if not isinstance(mapping, dict):
        raise ApiError(422, "validation_error", "Send {mapping: {field: column}}.")
    # validate required fields, but keep the full mapping — the import job also
    # needs action / downtime_min / technician, and the closure below captures
    # this exact dict.
    for f in log_import._REQUIRED:
        if mapping.get(f) is None:
            raise ApiError(422, "validation_error", f"'{f}' must be mapped to a column.")

    with db() as conn:
        row = conn.execute(
            "select file_name, file_path, file_hash, status, detected from log_imports where id = %s and tenant_id = %s",
            (import_id, user.tenant_id),
        ).fetchone()
        if not row:
            raise ApiError(404, "not_found", "Import not found.")
        file_name, file_path, fhash, status, detected = row
        columns = (detected or {}).get("columns", [])
        for f in log_import._REQUIRED:
            if mapping[f] not in columns:
                raise ApiError(422, "validation_error", f"Column '{mapping[f]}' is not in the file.")
        if status == "done" and fhash:
            dup = conn.execute(
                "select id from log_imports where tenant_id = %s and file_hash = %s and status = 'done' and id <> %s limit 1",
                (user.tenant_id, fhash, import_id),
            ).fetchone()
            if dup and not force:
                raise ApiError(409, "already_imported", "This exact file was already imported.")

    # re-parse with the confirmed mapping; re-check row limits
    try:
        data = storage.download(file_path)
        log_import.analyse(user.tenant_id, file_name or "upload.xlsx", data)
    except ValueError as e:
        raise ApiError(422, "validation_error", str(e)) from None
    except Exception:
        raise ApiError(500, "internal_error", "Could not read the uploaded file.") from None

    with db() as conn:
        conn.execute(
            "update log_imports set column_mapping = %s::jsonb, status = 'mapping' where id = %s",
            (json.dumps(mapping), import_id),
        )
    job_id = jobs.create_job(
        user.tenant_id, "import_logs", import_id,
    )
    background.add_task(
        jobs.run_job, job_id,
        lambda: log_import.import_rows(import_id, user.tenant_id, mapping, job_id),
    )
    return {"job_id": job_id}


@router.get("/log-imports/{import_id}")
def get_log_import(import_id: str, _: CurrentUser = Depends(require_admin)) -> dict:
    with db() as conn:
        row = conn.execute(
            """select id, status, column_mapping, rows_ok, rows_skipped, detected, file_name, created_at
               from log_imports where id = %s and tenant_id = %s""",
            (import_id, _.tenant_id),
        ).fetchone()
    if not row:
        raise ApiError(404, "not_found", "Import not found.")
    detected = row[5] or {}
    return {
        "import_id": str(row[0]),
        "status": row[1],
        "mapping": row[2],
        "rows_ok": row[3],
        "rows_skipped": row[4],
        "skipped": detected.get("skipped", []),
        "file_name": row[6],
        "created_at": row[7].isoformat(),
    }


# ===== jobs + reindex =====

@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: CurrentUser = Depends(require_admin)) -> dict:
    with db() as conn:
        row = conn.execute(
            "select type, status, progress, error, updated_at from jobs where id = %s and tenant_id = %s",
            (job_id, user.tenant_id),
        ).fetchone()
    if not row:
        raise ApiError(404, "not_found", "Job not found.")
    return {"type": row[0], "status": row[1], "progress": row[2], "error": row[3], "updated_at": row[4].isoformat()}


@router.post("/reindex", status_code=202)
def reindex(background: BackgroundTasks, user: CurrentUser = Depends(require_admin)) -> dict:
    if not embeddings.ready():
        raise ApiError(503, "embed_not_ready", "The embedding model is still loading. Try again shortly.")

    def _reindex() -> None:
        from app.services import knowledge

        knowledge.reembed_tenant(user.tenant_id)

    job_id = jobs.create_job(user.tenant_id, "reindex", None)
    background.add_task(jobs.run_job, job_id, _reindex)
    return {"job_id": job_id}
