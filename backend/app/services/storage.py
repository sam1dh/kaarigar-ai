"""Supabase Storage uploads for manuals and log files (service-role client).

Paths: documents/{tenant_id}/{document_id}.pdf, imports/{tenant_id}/{import_id}.{ext}
"""

from __future__ import annotations

from app.core.supabase import admin_client


def upload(path: str, data: bytes, content_type: str) -> None:
    client = admin_client()
    client.storage.from_("documents" if path.startswith("documents/") else "imports").upload(
        path, data, {"content-type": content_type, "upsert": "true"}
    )


def download(path: str) -> bytes:
    client = admin_client()
    bucket = "documents" if path.startswith("documents/") else "imports"
    return client.storage.from_(bucket).download(path)


def delete(path: str) -> None:
    client = admin_client()
    bucket = "documents" if path.startswith("documents/") else "imports"
    # remove() takes a list and is idempotent for missing objects
    client.storage.from_(bucket).remove([path])
