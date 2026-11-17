"""documents → chunks pipeline (runs as a job, or directly from the seed script)."""

from __future__ import annotations

import json
import logging

import pymupdf

from app.core.config import get_settings
from app.core.db import db
from app.services import chunking, embeddings, jobs, storage

logger = logging.getLogger("kaarigar.pdf")


def _fail(document_id: str, error: str) -> None:
    with db() as conn:
        conn.execute(
            "update documents set status = 'failed', error = %s where id = %s",
            (error, document_id),
        )


def ingest_document(document_id: str, job_id: str | None = None) -> None:
    s = get_settings()

    def progress(pct: int) -> None:
        if job_id:
            jobs.update(job_id, progress=pct)

    with db() as conn:
        row = conn.execute(
            "select id, tenant_id, model_id, title, file_path from documents where id = %s",
            (document_id,),
        ).fetchone()
    if not row:
        _fail(document_id, "document not found")
        return
    _id, tenant_id, model_id, title, file_path = row
    tenant_id = str(tenant_id)

    # 1. download + validate
    try:
        data = storage.download(file_path)
    except Exception as e:
        logger.info("document %s: download failed (%s)", document_id, type(e).__name__)
        _fail(document_id, "File not found in storage.")
        return

    if not data.startswith(b"%PDF"):
        _fail(document_id, "This file is not a PDF. Upload a .pdf file.")
        return
    if len(data) > s.max_pdf_mb * 1024 * 1024:
        _fail(document_id, f"File is larger than {s.max_pdf_mb} MB.")
        return

    import io

    try:
        doc = pymupdf.open(stream=io.BytesIO(data), filetype="pdf")
        if doc.needs_pass:
            _fail(document_id, "PDF is password protected. Remove the password and try again.")
            return
        if doc.page_count > s.max_pdf_pages:
            _fail(document_id, f"PDF has more than {s.max_pdf_pages} pages.")
            return
        pages_native = [(p.get_text() or "", _image_coverage(p)) for p in doc]
        n_pages = doc.page_count
        doc.close()
    except Exception:
        logger.exception("document %s: unreadable PDF", document_id)
        _fail(document_id, "Could not read the PDF. It may be corrupted.")
        return

    with db() as conn:
        conn.execute("update documents set status = 'parsing', pages = %s where id = %s", (n_pages, document_id))
    progress(5)

    # 2. chunk (OCR text may come from pymupdf4llm if Tesseract exists)
    pdf_path = _tmp_pdf(data)
    try:
        chunks, _ = chunking.chunks_from_pdf(pdf_path)
    finally:
        import os

        os.unlink(pdf_path)

    # 3. scanned pages: native text < 100 chars AND image covers > 50%
    quality_notes: list[str] = []
    scanned = [i + 1 for i, (native, img) in enumerate(pages_native) if len(native.strip()) < 100 and img > 0.5]
    for pno in scanned:
        has_ocr = any(c["page"] == pno and c.get("meta", {}).get("ocr") for c in chunks)
        if has_ocr:
            quality_notes.append(f"Page {pno} is a scanned image. Text was read by OCR; check it.")
        else:
            quality_notes.append(f"Page {pno} is a scanned image with no text. It is not searchable.")
            chunks = [c for c in chunks if c["page"] != pno]
    if not chunks:
        _fail(document_id, "No readable text found in the PDF.")
        return

    progress(50)

    # 4. embed + save
    embed_texts = [f"{title} > {c['section']}\n{c['text']}" if c.get("section") else c["text"] for c in chunks]
    vectors = embeddings.embed_passages(embed_texts)
    progress(95)

    with db() as conn:
        conn.execute("delete from chunks where source_type = 'manual' and source_id = %s", (document_id,))
        for c, vec in zip(chunks, vectors, strict=True):
            meta = dict(c.get("meta") or {})
            meta["embed_model"] = s.embed_model
            conn.execute(
                """insert into chunks
                   (tenant_id, source_type, source_id, model_id, machine_id, section, text,
                    embedding, page, chunk_index, meta)
                   values (%s, 'manual', %s, %s, null, %s, %s, %s, %s, %s, %s)""",
                (
                    tenant_id,
                    document_id,
                    model_id,
                    c.get("section"),
                    c["text"],
                    list(map(float, vec)),
                    c.get("page"),
                    c["chunk_index"],
                    json.dumps(meta),                ),
            )
        conn.execute(
            "update documents set status = 'ready', quality_notes = %s where id = %s",
            ("\n".join(quality_notes) or None, document_id),
        )
    progress(100)
    logger.info(
        "document %s: %s chunks from %s pages, %s scanned page(s)",
        document_id, len(chunks), n_pages, len(scanned),
    )


def _image_coverage(page: pymupdf.Page) -> float:
    area = page.rect.width * page.rect.height
    if area <= 0:
        return 0.0
    covered = 0.0
    for img in page.get_images(full=True):
        try:
            rects = page.get_image_rects(img[0])
            for r in rects:
                covered += r.width * r.height
        except Exception:
            continue
    return min(covered / area, 1.0)


def _tmp_pdf(data: bytes) -> str:
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path
