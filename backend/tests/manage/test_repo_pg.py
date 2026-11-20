"""PostgresManageRepo + migration 0005 against a real, throwaway Postgres.

Skipped unless KAARIGAR_TEST_PG_DSN points at a LOCAL Postgres where the user may create databases, e.g.
    KAARIGAR_TEST_PG_DSN=postgresql://postgres@localhost:5432/postgres pytest tests/manage/test_repo_pg.py
Never point it at Supabase: it creates and drops its own database.
"""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

DSN = os.environ.get("KAARIGAR_TEST_PG_DSN")
pytestmark = [pytest.mark.pg, pytest.mark.skipif(not DSN, reason="KAARIGAR_TEST_PG_DSN not set")]

HERE = Path(__file__).resolve().parent


def _migration() -> Path:
    for base in [HERE, *HERE.parents]:
        p = base / "supabase" / "migrations" / "0005_phase4.sql"
        if p.exists():
            return p
    raise FileNotFoundError("supabase/migrations/0005_phase4.sql")


U = lambda i: str(uuid.UUID(int=i))  # noqa: E731
T, T2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
SUP, SUP2, TECH, EXPERT, OTHER = U(1), U(2), U(412), U(107), U(9001)
MODEL, HP07, CNC03, HP_OTHER = U(500), U(7), U(3), U(70)
DOC, LOG, IMPORT = U(800), U(900), U(950)
R1, R2, R_PENDING = U(1001), U(1002), U(1003)
Q1, Q2, Q3, Q4 = U(2001), U(2002), U(2003), U(2004)
ESC = U(3001)


@pytest.fixture(scope="module")
def db():
    import psycopg

    name = f"kaarigar_p4_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f'create database "{name}"')
    dsn = psycopg.conninfo.make_conninfo(DSN, dbname=name)
    try:
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("create extension if not exists pg_trgm")
            c.execute("create extension if not exists pgcrypto")
            c.execute((HERE / "sql" / "base_schema.sql").read_text())
            mig = _migration().read_text()
            c.execute(mig)
            c.execute(mig)            # must be safe to run twice
            c.execute(f"""
              insert into tenants (id, name, slug) values ('{T}', 'Shree', 'shree'), ('{T2}', 'Other', 'other');
              insert into users (id, tenant_id, name, employee_id, role, is_admin, language) values
                ('{SUP}', '{T}', 'Suresh Kulkarni', null, 'supervisor', true, 'hi-IN'),
                ('{SUP2}', '{T}', 'Meena Joshi', null, 'supervisor', false, 'mr-IN'),
                ('{TECH}', '{T}', 'Amit Kale', 'SH-0412', 'technician', false, 'hi-IN'),
                ('{EXPERT}', '{T}', 'Ramesh Patil', 'SH-0107', 'expert', false, 'mr-IN'),
                ('{OTHER}', '{T2}', 'Elsewhere', 'SH-0412', 'supervisor', true, 'en-IN');
              insert into auth.users (id, email, last_sign_in_at) values
                ('{SUP}', 'suresh@shree.in', now()), ('{TECH}', 'sh-0412@shree.employees.kaarigar.app', now() - interval '1 day');
              insert into machine_models (id, tenant_id, model, type) values ('{MODEL}', '{T}', 'HPX-200', 'hydraulic press');
              insert into machines (id, tenant_id, model_id, code, name, line) values
                ('{HP07}', '{T}', '{MODEL}', 'HP-07', 'Hydraulic press', 'Line 2'),
                ('{CNC03}', '{T}', null, 'CNC-03', 'CNC lathe', 'Line 1'),
                ('{HP_OTHER}', '{T2}', null, 'HP-07', 'Theirs', null);
              insert into documents (id, tenant_id, model_id, title, type, file_path, status, pages, quality_notes) values
                ('{DOC}', '{T}', '{MODEL}', 'HPX-200 Service Manual', 'manual', 'x.pdf', 'ready', 4, 'Page 4 scanned');
              insert into chunks (tenant_id, source_type, source_id, text) values
                ('{T}', 'manual', '{DOC}', 'Relief valve setting 180 bar'), ('{T}', 'manual', '{DOC}', 'Seal kit'),
                ('{T}', 'record', '{R1}', 'pressure not building reset relief valve');
              insert into log_imports (id, tenant_id, file_name, status, rows_ok, rows_skipped, created_by) values
                ('{IMPORT}', '{T}', 'shree_log.xlsx', 'done', 56, 4, '{SUP}');
              insert into maintenance_logs (id, tenant_id, machine_id, import_id, date, fault, action, downtime_min, technician) values
                ('{LOG}', '{T}', '{HP07}', '{IMPORT}', '2025-10-03', 'pressure low', 'seal kit', 150, 'Vijay'),
                (gen_random_uuid(), '{T}', '{HP07}', '{IMPORT}', '2025-06-01', 'oil leak', 'hose', 60, 'Vijay');
              insert into repair_records (id, tenant_id, machine_id, author_id, fields, status, reviewed_by, reviewed_at, submitted_at) values
                ('{R1}', '{T}', '{HP07}', '{EXPERT}', '{{"symptom":"pressure not building","fix":"reset relief valve"}}', 'approved', '{SUP}', now() - interval '2 days', now() - interval '3 days'),
                ('{R2}', '{T}', '{CNC03}', '{EXPERT}', '{{"symptom":"chatter","fix":"tighten gib"}}', 'approved', '{SUP}', now() - interval '20 days', now() - interval '21 days'),
                ('{R_PENDING}', '{T}', '{HP07}', '{TECH}', '{{}}', 'pending', null, null, now());
              insert into queries (id, tenant_id, user_id, machine_id, question_en, status, input_mode, escalated, first_token_ms, citations, created_at) values
                ('{Q1}', '{T}', '{TECH}', '{HP07}', 'pressure low', 'answered', 'voice', false, 1500,
                   '[{{"ref":"E1","source_type":"record","source_id":"{R1}"}},{{"ref":"M1","source_type":"manual","source_id":"{DOC}"}}]', now() - interval '1 day'),
                ('{Q2}', '{T}', '{TECH}', '{HP07}', 'pressure again', 'answered', 'text', false, 2500,
                   '[{{"ref":"E1","source_type":"record","source_id":"{R1}"}},{{"ref":"H1","source_type":"history","source_id":"{LOG}"}}]', now() - interval '2 days'),
                ('{Q3}', '{T}', '{TECH}', '{CNC03}', 'AC trips', 'no_answer', 'voice', true, null, '[]', now() - interval '3 days'),
                ('{Q4}', '{T}', '{TECH}', '{HP07}', 'old one', 'answered', 'voice', false, 900, '[]', now() - interval '60 days');
              insert into feedback (tenant_id, query_id, user_id, outcome) values ('{T}', '{Q1}', '{TECH}', 'fixed'), ('{T}', '{Q2}', '{TECH}', 'not_fixed');
              insert into escalations (id, tenant_id, query_id, asked_by, machine_id, assigned_to, assigned_at, status) values
                ('{ESC}', '{T}', '{Q3}', '{TECH}', '{CNC03}', '{EXPERT}', now(), 'open');
            """)

        @contextmanager
        def conn_factory():
            with psycopg.connect(dsn) as conn:
                yield conn

        from app.manage.repo import PostgresManageRepo

        yield PostgresManageRepo(conn_factory), dsn
    finally:
        with psycopg.connect(DSN, autocommit=True) as admin:
            admin.execute(f'drop database if exists "{name}" with (force)')


@pytest.fixture
def repo(db):
    return db[0]


def scalar(dsn, sql):
    import psycopg

    with psycopg.connect(dsn) as c:
        return c.execute(sql).fetchone()[0]


# --------------------------------------------------------------- migration

def test_migration_columns_and_rls(db):
    _, dsn = db
    cols = {r for r in [scalar(dsn, f"select count(*) from information_schema.columns where table_name='{t}' and column_name='{c}'")
                        for t, c in [("users", "deactivated_at"), ("users", "created_by"), ("machines", "archived_at"),
                                     ("machines", "sticker_printed_at"), ("repair_records", "archived_at"),
                                     ("repair_records", "archived_by")]]}
    assert cols == {1}
    assert scalar(dsn, "select relrowsecurity from pg_class where relname='admin_audit'") is True
    assert scalar(dsn, "select count(*) from pg_indexes where indexname='queries_citations_gin_idx'") == 1


# --------------------------------------------------------------- people

def test_people_list_joins_auth_and_counts(repo):
    rows = repo.list_people(T)
    assert [r["name"] for r in rows][:2] == ["Meena Joshi", "Suresh Kulkarni"]     # supervisors first, by name
    assert OTHER not in {str(r["id"]) for r in rows}
    ramesh = next(r for r in rows if str(r["id"]) == EXPERT)
    assert ramesh["approved_notes"] == 2 and ramesh["email"] is None
    amit = next(r for r in rows if str(r["id"]) == TECH)
    assert amit["email"].startswith("sh-0412@") and amit["last_question_at"] is not None


def test_people_crud_and_admin_count(repo):
    assert repo.employee_id_taken(T, "sh-0412") and not repo.employee_id_taken(T, "SH-0999")
    new = U(4444)
    repo.insert_person(user_id=new, tenant_id=T, name="Vijay More", employee_id="SH-0521", role="technician",
                       is_admin=False, language="mr-IN", created_by=SUP)
    p = repo.get_person(T, new)
    assert p["name"] == "Vijay More" and p["deactivated_at"] is None
    assert repo.get_person(T2, new) is None
    repo.update_person(T, new, role="expert", language="hi-IN")
    assert repo.get_person(T, new)["role"] == "expert"
    with pytest.raises(ValueError):
        repo.update_person(T, new, employee_id="X-1")
    assert repo.active_admin_count(T) == 1
    repo.update_person(T, SUP2, is_admin=True)
    assert repo.active_admin_count(T) == 2
    repo.update_person(T, SUP2, is_admin=False)


def test_deactivate_unassigns_open_escalations(db, repo):
    _, dsn = db
    assert repo.set_deactivated(T, EXPERT, True) == 1
    assert scalar(dsn, f"select assigned_to from escalations where id='{ESC}'") is None
    assert repo.get_person(T, EXPERT)["deactivated_at"] is not None
    assert repo.set_deactivated(T2, EXPERT, False) == 0          # other plant can't touch
    repo.set_deactivated(T, EXPERT, False)
    assert repo.get_person(T, EXPERT)["deactivated_at"] is None


def test_audit(repo):
    repo.audit(T, SUP, "person_added", "user", TECH, {"role": "technician"})
    repo.audit(T2, OTHER, "machine_added", "machine", HP_OTHER, {})
    items = repo.audit_list(T, 10)
    assert items[0]["action"] == "person_added" and items[0]["actor_name"] == "Suresh Kulkarni"
    assert all(i["action"] != "machine_added" for i in items)


# --------------------------------------------------------------- machines

def test_list_machines_with_stats(repo):
    rows = repo.list_machines(T, False)
    assert [r["code"] for r in rows] == ["CNC-03", "HP-07"]
    hp = rows[1]
    assert hp["model"] == "HPX-200" and hp["approved_records"] == 1 and hp["questions_30d"] == 2
    assert str(hp["last_breakdown_date"]) == "2025-10-03" and hp["last_breakdown_fault"] == "pressure low"
    assert len(hp["qr_token"]) == 24


def test_machine_lifecycle(repo):
    assert repo.find_model(T, "hpx-200")["model"] == "HPX-200" and repo.find_model(T2, "HPX-200") is None
    m = repo.insert_model(T, "AirPro 7", "compressor", None)
    mid = repo.insert_machine(T, "AC-01", "Air compressor", "Utility", str(m["id"]))
    assert repo.get_machine(T, mid)["model"] == "AirPro 7" and repo.get_machine(T2, mid) is None
    repo.update_machine(T, mid, name="Compressor", line=None)
    row = repo.get_machine(T, mid)
    assert row["name"] == "Compressor" and row["line"] is None
    old = row["qr_token"]
    repo.mark_printed(T, [mid])
    assert repo.get_machine(T, mid)["sticker_printed_at"] is not None
    new = repo.renew_qr(T, mid)
    row = repo.get_machine(T, mid)
    assert new != old and row["qr_token"] == new and row["sticker_printed_at"] is None
    repo.set_machine_archived(T, mid, True)
    assert mid not in {str(r["id"]) for r in repo.list_machines(T, False)}
    assert mid in {str(r["id"]) for r in repo.list_machines(T, True)}
    repo.set_machine_archived(T, mid, False)
    by_ids = repo.machines_by_ids(T, [mid, HP07, HP_OTHER])
    assert [r["code"] for r in by_ids] == ["AC-01", "HP-07"]
    assert {r["code"] for r in repo.machine_codes(T)} >= {"HP-07", "CNC-03", "AC-01"}
    assert repo.model_in_tenant(T, str(m["id"])) and not repo.model_in_tenant(T2, str(m["id"]))


# --------------------------------------------------------------- knowledge

def test_knowledge_stats(repo):
    s = repo.knowledge_stats(T)
    assert s["records"] == 2 and s["records_week"] == 1 and s["manual_sections"] == 2
    assert s["documents"] == 1 and s["history"] == 2 and s["questions_30d"] == 3 and s["answered_30d"] == 2


def test_knowledge_lists_with_used_counts(repo):
    recs = repo.knowledge_records(T, machine=None, q=None, archived=False, limit=10)
    assert [str(r["id"]) for r in recs] == [R1, R2]
    assert recs[0]["used"] == 2 and recs[1]["used"] == 0 and recs[0]["author_name"] == "Ramesh Patil"
    assert [str(r["id"]) for r in repo.knowledge_records(T, machine="cnc-03", q=None, archived=False, limit=10)] == [R2]
    assert [str(r["id"]) for r in repo.knowledge_records(T, machine=None, q="RELIEF", archived=False, limit=10)] == [R1]
    docs = repo.knowledge_documents(T, machine=None, q=None, limit=10)
    assert docs[0]["sections"] == 2 and docs[0]["used"] == 1
    assert repo.knowledge_documents(T, machine=None, q="180 bar", limit=10)        # searches inside sections
    assert repo.knowledge_documents(T, machine="CNC-03", q=None, limit=10) == []   # different model
    logs = repo.knowledge_logs(T, machine="HP-07", q=None, limit=10)
    assert str(logs[0]["id"]) == LOG and logs[0]["used"] == 1
    assert len(repo.knowledge_logs(T, machine=None, q="leak", limit=10)) == 1
    assert repo.knowledge_records(T2, machine=None, q=None, archived=False, limit=10) == []


def test_archive_record_removes_chunk(db, repo):
    _, dsn = db
    assert repo.archive_record(T, R1, SUP) == 1
    assert scalar(dsn, f"select count(*) from chunks where source_id='{R1}'") == 0
    assert repo.get_record(T, R1)["archived_at"] is not None
    assert repo.archive_record(T, R1, SUP) == 0
    assert [str(r["id"]) for r in repo.knowledge_records(T, machine=None, q=None, archived=True, limit=10)] == [R1]
    assert repo.archive_record(T, R_PENDING, SUP) == 0            # only approved
    assert repo.unarchive_record(T, R1) == 1
    assert repo.get_record(T, R1)["archived_at"] is None
    assert repo.get_record(T2, R1) is None


# --------------------------------------------------------------- analytics + logs

def test_analytics(repo):
    a = repo.analytics(T, 7)
    t = a["totals"]
    assert (t["questions"], t["answered"], t["no_answer"], t["voice"], t["escalated"]) == (3, 2, 1, 2, 1)
    assert float(t["first_word_ms"]) == 2000.0
    assert (a["feedback"]["fixed"], a["feedback"]["not_fixed"]) == (1, 1)
    assert a["escalations"]["created"] == 1 and a["escalations"]["open_now"] == 1
    assert a["notes"]["pending_now"] == 1 and a["notes"]["approved"] == 1
    assert len(a["per_day"]) == 7 and sum(d["questions"] for d in a["per_day"]) == 3
    assert a["machines"][0]["code"] == "HP-07" and a["machines"][0]["questions"] == 2
    assert [str(g["id"]) for g in a["gaps"]] == [Q3] and a["gaps"][0]["escalation_status"] == "open"
    ramesh = next(p for p in a["team"] if str(p["id"]) == EXPERT)
    assert ramesh["knowledge_used"] == 2 and ramesh["notes_approved"] == 1
    assert repo.analytics(T, 90)["totals"]["questions"] == 4
    assert repo.analytics(T2, 30)["totals"]["questions"] == 0


def test_logs(repo):
    li = repo.list_log_imports(T, 5)
    assert li[0]["file_name"] == "shree_log.xlsx" and li[0]["created_by_name"] == "Suresh Kulkarni"
    logs = repo.list_maintenance_logs(T, "hp-07", 10)
    assert [str(l["date"]) for l in logs] == ["2025-10-03", "2025-06-01"] and logs[0]["file_name"] == "shree_log.xlsx"
    assert repo.list_log_imports(T2, 5) == []


# --------------------------------------------------------------- API through the real repo

def test_api_end_to_end_with_real_repo(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.capture import adapters as capture_adapters
    from app.manage import deps
    from app.manage.adapters import ManageUser
    from app.manage.router_machines import router as machines_router
    from app.manage.router_people import router as people_router

    from .fakes import FakeAuth

    repo, _ = db
    app = FastAPI()
    app.include_router(people_router)
    app.include_router(machines_router)
    auth = FakeAuth()
    app.dependency_overrides[capture_adapters.capture_user] = lambda: ManageUser(
        id=SUP, tenant_id=T, role="supervisor", is_admin=True, language="hi-IN", name="Suresh Kulkarni")
    app.dependency_overrides[deps.get_repo] = lambda: repo
    app.dependency_overrides[deps.get_auth_admin] = lambda: auth
    c = TestClient(app)

    r = c.post("/admin/people", json={"name": "Kiran Shinde", "role": "technician", "employee_id": "SH-0777"})
    assert r.status_code == 201, r.text
    pid = r.json()["person"]["id"]
    assert r.json()["person"]["status"] == "new"
    assert c.post(f"/admin/people/{pid}/deactivate").json()["status"] == "deactivated"
    assert c.post("/admin/people", json={"name": "Dup", "role": "technician", "employee_id": "sh-0777"}).status_code == 409

    r = c.post("/admin/machines", json={"code": "grd 4", "new_model": {"model": "G-400"}})
    assert r.status_code == 201, r.text
    assert r.json()["code"] == "GRD-4" and r.json()["model"]["model"] == "G-400"
    assert c.post("/admin/machines", json={"code": "HP 7"}).status_code == 409
    s = c.post("/admin/machines/stickers", json={"machine_ids": [r.json()["id"]]}).json()["items"][0]
    assert s["svg"].startswith("<svg") and s["code"] == "GRD-4"
