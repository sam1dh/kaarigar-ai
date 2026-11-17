"""Integration tests — need the real Supabase project + the Phase 1 seed.

Run with:  pytest -m integration
Every test that mutates state restores it (deletes what it created).
"""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.integration

client = TestClient(app)
PLANT = "shree"
AMIT = {"plant_code": PLANT, "employee_id": "SH-0412", "pin": "482913"}


@pytest.fixture(scope="module", autouse=True)
def _embed_model_ready() -> None:
    """TestClient does not run the app lifespan; start the model load ourselves."""
    from app.services import embeddings

    embeddings.wait_ready(300)


def _supervisor_token() -> str:
    """Suresh signs in with email + password (SEED_ADMIN_PASSWORD in the root .env)."""
    from app.core.config import get_settings
    from app.core.supabase import anon_client

    settings = get_settings()
    res = anon_client().auth.sign_in_with_password(
        {"email": "suresh@shreehydraulics.in", "password": settings.seed_admin_password}
    )
    assert res.session is not None
    return res.session.access_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def suresh_token() -> str:
    return _supervisor_token()


@pytest.fixture(scope="module")
def amit_token() -> str:
    res = client.post("/auth/pin-login", json=AMIT)
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


# ===== 403s: Amit (technician) on /admin/* and /dev/* =====

def test_amit_forbidden_on_admin_and_dev(amit_token: str) -> None:
    for path in ("/admin/ping", "/admin/documents", "/admin/machine-models", "/dev/search?q=pump", "/dev/stats"):
        res = client.get(path, headers=_auth(amit_token))
        assert res.status_code == 403, (path, res.status_code, res.text)


def test_amit_pin_login_profile(amit_token: str) -> None:
    res = client.get("/auth/me", headers=_auth(amit_token))
    assert res.status_code == 200
    profile = res.json()
    assert profile["employee_id"] == "SH-0412"
    assert profile["role"] in ("technician", "operator")


# ===== supervisor access =====

def test_supervisor_dev_endpoints(suresh_token: str) -> None:
    res = client.get("/dev/search", params={"q": "pump thak thak", "machine": "HP-07"}, headers=_auth(suresh_token))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["machine"] == "HP-07"
    assert body["results"], "expected results for the seeded DoD query"

    res = client.get("/dev/stats", headers=_auth(suresh_token))
    assert res.status_code == 200
    stats = res.json()
    assert stats["documents"] >= 3
    assert stats["logs"] == 56
    assert stats["records"] == 26
    assert stats["chunks"]["manual"] >= 30


def test_dev_search_validation(suresh_token: str, amit_token: str) -> None:
    res = client.get("/dev/search", params={"q": "x"}, headers=_auth(suresh_token))
    assert res.status_code == 422  # q too short
    res = client.get("/dev/search", params={"q": "pump", "machine": "NOPE-99"}, headers=_auth(suresh_token))
    assert res.status_code == 404  # unknown machine
    res = client.get("/dev/search", headers=_auth(amit_token))
    assert res.status_code == 403, (res.status_code, res.text)


# ===== DoD queries =====

def test_dod_pump_thak_thak(suresh_token: str) -> None:
    res = client.get("/dev/search", params={"q": "pump thak thak", "machine": "HP-07"}, headers=_auth(suresh_token))
    assert res.status_code == 200
    results = res.json()["results"]
    assert results, "no results"
    top = results[0]
    assert top["source_type"] == "record"
    assert top["meta"].get("seed_key") == "R02"
    labels = {r["label"] for r in results[:8]}
    assert {"E", "M", "H"} <= labels, f"expected E/M/H mix, got {labels}"


def test_dod_error_code_e05(suresh_token: str) -> None:
    res = client.get("/dev/search", params={"q": "E05 alarm", "machine": "HP-07"}, headers=_auth(suresh_token))
    assert res.status_code == 200
    results = res.json()["results"]
    top_texts = " ".join(r["text"] for r in results[:3]).lower()
    assert "e-05" in top_texts


# ===== tenant isolation =====

def test_tenant_isolation(suresh_token: str) -> None:
    """A chunk planted in another tenant must never surface in a shree search."""
    from app.core.db import db

    marker = f"zzxq isolated chunk {uuid.uuid4().hex[:8]} verydistinctive"
    slug = f"iso-test-{uuid.uuid4().hex[:8]}"
    tenant_id = machine_id = doc_id = chunk_id = None
    try:
        with db() as conn:
            tenant_id = str(
                conn.execute(
                    "insert into tenants (name, slug) values ('Iso Test', %s) returning id",
                    (slug,),
                ).fetchone()[0]
            )
            model_id = str(
                conn.execute(
                    "insert into machine_models (tenant_id, model) values (%s, 'ZZX-1') returning id",
                    (tenant_id,),
                ).fetchone()[0]
            )
            machine_id = str(
                conn.execute(
                    "insert into machines (tenant_id, model_id, code, name) values (%s, %s, 'ZZX1', 'Iso Machine') returning id",
                    (tenant_id, model_id),
                ).fetchone()[0]
            )
            doc_id = str(
                conn.execute(
                    """insert into documents (id, tenant_id, model_id, title, type, file_path, status, created_by)
                       values (%s, %s, %s, 'Iso Doc', 'manual', 'documents/none.pdf', 'ready', null) returning id""",
                    (str(uuid.uuid4()), tenant_id, model_id),
                ).fetchone()[0]
            )
            chunk_id = str(
                conn.execute(
                    """insert into chunks (tenant_id, source_type, source_id, machine_id, model_id, section, text)
                       values (%s, 'manual', %s, %s, %s, 'Iso', %s) returning id""",
                    (tenant_id, doc_id, machine_id, model_id, marker),
                ).fetchone()[0]
            )

        # positive control: searching the isolated tenant's own scope finds it (direct service call)
        from app.services import embeddings
        from app.services import search as search_svc

        embeddings.wait_ready()
        out = search_svc.search(tenant_id, marker, k=5)
        assert any(r["chunk_id"] == chunk_id for r in out["results"])

        # negative: the same query against shree must NOT return the foreign chunk
        res = client.get("/dev/search", params={"q": marker}, headers=_auth(suresh_token))
        assert res.status_code == 200
        assert all(r["chunk_id"] != chunk_id for r in res.json()["results"])
    finally:
        with db() as conn:
            if chunk_id:
                conn.execute("delete from chunks where id = %s", (chunk_id,))
            if doc_id:
                conn.execute("delete from documents where id = %s", (doc_id,))
            if machine_id:
                conn.execute("delete from machines where id = %s", (machine_id,))
            if tenant_id:
                conn.execute("delete from chunks where tenant_id = %s", (tenant_id,))
                conn.execute("delete from machine_models where tenant_id = %s", (tenant_id,))
                conn.execute("delete from machines where tenant_id = %s", (tenant_id,))
                conn.execute("delete from documents where tenant_id = %s", (tenant_id,))
                conn.execute("delete from tenants where id = %s", (tenant_id,))


# ===== fake PDF upload (.txt renamed to .pdf) =====

def test_fake_pdf_fails(suresh_token: str) -> None:
    from app.core.db import db

    model_id = None
    with db() as conn:
        row = conn.execute(
            "select mm.id from machine_models mm join tenants t on t.id = mm.tenant_id "
            "where t.slug = %s and mm.model = 'HPX-200'",
            (PLANT,),
        ).fetchone()
        model_id = str(row[0])

    data = f"this is not a pdf at all, just text renamed to .pdf {uuid.uuid4().hex}".encode()
    title = f"ZZ Test fake pdf {uuid.uuid4().hex[:8]}"
    res = client.post(
        "/admin/documents",
        headers=_auth(suresh_token),
        files={"file": ("fake.pdf", data, "application/pdf")},
        data={"title": title, "type": "manual", "model_id": model_id},
    )
    assert res.status_code == 202, res.text  # accepted, processing is async
    document_id = res.json()["document_id"]

    try:
        # poll until the background ingest marks it failed
        status = None
        for _ in range(30):
            time.sleep(1)
            res = client.get(f"/admin/documents/{document_id}", headers=_auth(suresh_token))
            if res.status_code == 200:
                status = res.json()["status"]
                if status in ("ready", "failed"):
                    break
        assert status == "failed", f"expected the fake pdf to fail, got {status}"
    finally:
        res = client.delete(f"/admin/documents/{document_id}", headers=_auth(suresh_token))
        assert res.status_code in (204, 200, 404)
