"""PostgresAssistRepo + migration 0004 against a real, throwaway Postgres.

Skipped unless KAARIGAR_TEST_PG_DSN points at a LOCAL Postgres where the user may create databases, e.g.
    KAARIGAR_TEST_PG_DSN=postgresql://postgres@localhost:5432/postgres pytest tests/assist/test_repo_pg.py
Never point it at Supabase: it creates and drops its own database.
It builds a stand-in for 0001-0003 (sql/base_schema.sql), runs 0004 twice, then exercises every query.
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
        p = base / "supabase" / "migrations" / "0004_phase3.sql"
        if p.exists():
            return p
    raise FileNotFoundError("supabase/migrations/0004_phase3.sql")


T = "11111111-1111-1111-1111-111111111111"
T2 = "22222222-2222-2222-2222-222222222222"
TECH, EXPERT, EXPERT2, SUP = (str(uuid.UUID(int=i)) for i in (412, 107, 233, 1))
OTHER = str(uuid.UUID(int=9001))
MODEL = str(uuid.UUID(int=500))
HP07, HP02, CNC = (str(uuid.UUID(int=i)) for i in (7, 2, 3))
DOC = str(uuid.UUID(int=800))
LOG = str(uuid.UUID(int=900))
R_APPROVED = str(uuid.UUID(int=1001))


@pytest.fixture(scope="module")
def db():
    import psycopg

    name = f"kaarigar_p3_{uuid.uuid4().hex[:8]}"
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
              insert into users (id, tenant_id, name, employee_id, role, language) values
                ('{TECH}', '{T}', 'Amit Kale', 'SH-0412', 'technician', 'hi-IN'),
                ('{EXPERT}', '{T}', 'Ramesh Patil', 'SH-0107', 'expert', 'mr-IN'),
                ('{EXPERT2}', '{T}', 'Anil Deshmukh', 'SH-0233', 'expert', 'hi-IN'),
                ('{SUP}', '{T}', 'Suresh Kulkarni', null, 'supervisor', 'hi-IN'),
                ('{OTHER}', '{T2}', 'Elsewhere', null, 'expert', 'en-IN');
              insert into machine_models (id, tenant_id, model, type) values ('{MODEL}', '{T}', 'HPX-200', 'hydraulic press');
              insert into machines (id, tenant_id, model_id, code, name, line, qr_token) values
                ('{HP07}', '{T}', '{MODEL}', 'HP-07', 'Hydraulic press', 'Line 2', 'aaaa1111bbbb2222cccc3333'),
                ('{HP02}', '{T}', '{MODEL}', 'HP-02', 'Hydraulic press', 'Line 1', 'dddd4444eeee5555ffff6666'),
                ('{CNC}', '{T}', null, 'CNC-03', 'CNC lathe', 'Line 1', '0000aaaa1111bbbb2222cccc');
              insert into repair_records (id, tenant_id, machine_id, author_id, status, fields, language) values
                ('{R_APPROVED}', '{T}', '{HP02}', '{EXPERT2}', 'approved', '{{"fix": "x"}}', 'hi-IN');
              insert into documents (id, tenant_id, model_id, title, type, file_path, status, pages) values
                ('{DOC}', '{T}', '{MODEL}', 'HPX-200 Service Manual', 'manual', 'shree/hpx.pdf', 'ready', 4);
              insert into chunks (tenant_id, source_type, source_id, model_id, section, text, page, chunk_index) values
                ('{T}', 'manual', '{DOC}', '{MODEL}', 'Troubleshooting', 'Check relief valve 210 bar', 3, 1),
                ('{T}', 'manual', '{DOC}', '{MODEL}', 'Troubleshooting', 'Pressure not building', 3, 0),
                ('{T}', 'manual', '{DOC}', '{MODEL}', 'Specs', 'Max 210 bar', 1, 0);
              insert into maintenance_logs (id, tenant_id, machine_id, date, fault, action, downtime_min) values
                ('{LOG}', '{T}', '{HP07}', '2025-10-03', 'pressure low', 'seal kit', 150);
            """)
        yield dsn
    finally:
        with psycopg.connect(DSN, autocommit=True) as admin:
            admin.execute(f'drop database if exists "{name}" with (force)')


@pytest.fixture(scope="module")
def repo(db):
    import psycopg

    from app.assist.repo import PostgresAssistRepo

    @contextmanager
    def conn():
        with psycopg.connect(db) as c:
            yield c

    r = PostgresAssistRepo(conn)
    r.dsn = db
    return r


def sql(repo, q, *args):
    import psycopg

    with psycopg.connect(repo.dsn, autocommit=True) as c:
        cur = c.execute(q, args)
        return cur.fetchall() if cur.description else None


def new_query(repo, user=TECH, machine=HP07, status_after="answered"):
    qid = str(uuid.uuid4())
    repo.create_query(query_id=qid, tenant_id=T, user_id=user, machine_id=machine, language="hi-IN",
                      input_mode="text", audio_path=None, question_original="प्रेशर नहीं")
    if status_after:
        repo.update_query(T, qid, status=status_after, answer_local="1. x [E1]",
                          answer_parts={"steps": [{"n": 1, "text": "x", "refs": ["E1"]}]},
                          sources=[{"ref": "E1"}], citations=[{"ref": "E1"}], confidence=0.9)
    return qid


def test_machines(repo):
    assert repo.machine_by_code(T, " hp-07 ")["model"] == "HPX-200"
    assert repo.machine_by_code(T2, "HP-07") is None
    assert repo.machine_by_qr(T, "aaaa1111bbbb2222cccc3333")["code"] == "HP-07"
    assert repo.machine_by_qr(T2, "aaaa1111bbbb2222cccc3333") is None


def test_query_lifecycle(repo):
    qid = new_query(repo)
    row = repo.get_query(T, qid)
    assert row["status"] == "answered" and row["machine_code"] == "HP-07" and row["user_name"] == "Amit Kale"
    assert row["answer_parts"]["steps"][0]["refs"] == ["E1"] and row["sources"] == [{"ref": "E1"}]
    assert row["escalation_id"] is None and row["feedback"] is None
    assert repo.get_query(T2, qid) is None
    assert qid in [r["id"].__str__() for r in repo.list_queries(T, TECH, 50)]
    with pytest.raises(ValueError):
        repo.update_query(T, qid, user_id=EXPERT)


def test_status_constraint(repo):
    import psycopg

    qid = new_query(repo)
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.update_query(T, qid, status="thinking")


def test_cancelled_questions_are_not_listed_and_stuck_ones_fail(repo):
    c = new_query(repo, status_after="cancelled")
    s = new_query(repo, status_after=None)               # still 'answering'
    ids = [str(r["id"]) for r in repo.list_queries(T, TECH, 50)]
    assert c not in ids and s in ids
    assert repo.mark_stuck_answering("server_restarted") >= 1
    assert repo.get_query(T, s)["status"] == "failed" and repo.get_query(T, s)["error"] == "server_restarted"


def test_feedback_upsert_is_one_row(repo):
    qid = new_query(repo)
    repo.upsert_feedback(T, qid, TECH, "not_fixed")
    repo.upsert_feedback(T, qid, TECH, "fixed")
    assert sql(repo, "select outcome from feedback where query_id = %s", qid) == [("fixed",)]
    assert repo.get_query(T, qid)["feedback"] == "fixed"


def test_pick_expert_prefers_who_fixed_this_model(repo):
    # Anil has an approved record on HP-02 (same model as HP-07); Ramesh has none
    assert repo.pick_expert(T, HP07, TECH) == EXPERT2
    assert repo.pick_expert(T, HP07, EXPERT2) == EXPERT       # never the asker
    assert repo.pick_expert(T, None, TECH) in (EXPERT, EXPERT2)
    assert repo.pick_expert(T2, None, TECH) == OTHER


def test_escalation_lifecycle_and_trigger(repo):
    qid = new_query(repo)
    eid = repo.create_escalation(tenant_id=T, query_id=qid, asked_by=TECH, machine_id=HP07, note="checked filter",
                                 assigned_to=EXPERT)
    assert eid and repo.create_escalation(tenant_id=T, query_id=qid, asked_by=TECH, machine_id=HP07, note=None,
                                          assigned_to=None) is None
    q = repo.get_query(T, qid)
    assert q["escalated"] is True and str(q["escalation_id"]) == eid and q["escalation_assigned_name"] == "Ramesh Patil"
    assert repo.escalation_id_for_query(T, qid) == eid

    e = repo.get_escalation(T, eid)
    assert e["status"] == "open" and e["assigned_at"] is not None and e["asked_by_name"] == "Amit Kale"
    assert e["question_original"] == "प्रेशर नहीं" and e["answer_status"] == "answered"
    assert e["reply_record_id"] is None and repo.get_escalation(T2, eid) is None

    # expert records a voice reply: a capture record linked to the escalation
    rid = str(uuid.uuid4())
    sql(repo, "insert into repair_records (id, tenant_id, machine_id, author_id, status, stage, language) "
              "values (%s, %s, %s, %s, 'draft', 'queued', 'mr-IN')", rid, T, HP07, EXPERT)
    repo.link_reply_record(T, rid, eid)
    assert sql(repo, "select source, escalation_id::text from repair_records where id = %s", rid) == [("escalation", eid)]
    e = repo.get_escalation(T, eid)
    assert str(e["reply_record_id"]) == rid and e["reply_record_status"] == "draft" and e["status"] == "open"

    # Phase 2 moves it to expert_review: still open; then the expert sends it -> pending -> trigger answers it
    sql(repo, "update repair_records set status = 'expert_review', stage = 'ready' where id = %s", rid)
    assert repo.get_escalation(T, eid)["status"] == "open"
    repo.set_reply_local(T, eid, {"language": "hi-IN", "record_id": None})
    sql(repo, "update repair_records set status = 'pending' where id = %s", rid)
    e = repo.get_escalation(T, eid)
    assert e["status"] == "answered" and str(e["new_record_id"]) == rid and str(e["replied_by"]) == EXPERT
    assert e["answered_at"] is not None and e["reply_local"] is None and e["replied_name"] == "Ramesh Patil"
    first_answer = e["answered_at"]
    # approval later doesn't touch it again
    sql(repo, "update repair_records set status = 'approved' where id = %s", rid)
    assert repo.get_escalation(T, eid)["answered_at"] == first_answer


def test_trigger_leaves_closed_escalations_alone(repo):
    qid = new_query(repo)
    eid = repo.create_escalation(tenant_id=T, query_id=qid, asked_by=TECH, machine_id=HP07, note=None, assigned_to=None)
    assert repo.close_escalation(T, eid, "not_needed")
    rid = str(uuid.uuid4())
    sql(repo, "insert into repair_records (id, tenant_id, machine_id, author_id, status, escalation_id, source) "
              "values (%s, %s, %s, %s, 'expert_review', %s, 'escalation')", rid, T, HP07, EXPERT, eid)
    sql(repo, "update repair_records set status = 'pending' where id = %s", rid)
    e = repo.get_escalation(T, eid)
    assert e["status"] == "closed" and e["close_reason"] == "not_needed" and e["new_record_id"] is None


def test_assign_reply_text_close_rules(repo):
    qid = new_query(repo)
    eid = repo.create_escalation(tenant_id=T, query_id=qid, asked_by=TECH, machine_id=HP07, note=None, assigned_to=None)
    assert repo.escalation_counts(T, EXPERT)["unassigned"] >= 1
    assert repo.assign_escalation(T, eid, EXPERT2)
    assert repo.escalation_counts(T, EXPERT2)["mine"] >= 1
    assert repo.set_reply_text(T, eid, EXPERT2, "Check fuse F3")
    e = repo.get_escalation(T, eid)
    assert e["status"] == "answered" and e["reply_text"] == "Check fuse F3" and str(e["replied_by"]) == EXPERT2
    assert not repo.set_reply_text(T, eid, EXPERT2, "again")          # only once
    assert not repo.assign_escalation(T, eid, EXPERT)                 # only open ones
    assert not repo.close_open_for_query(T, qid, "fixed_by_technician")   # not open any more
    assert repo.close_escalation(T, eid, "not_needed") and not repo.close_escalation(T, eid, "not_needed")


def test_listing_order_and_filters(repo):
    q1, q2 = new_query(repo), new_query(repo)
    a = repo.create_escalation(tenant_id=T, query_id=q1, asked_by=TECH, machine_id=HP07, note=None, assigned_to=EXPERT)
    b = repo.create_escalation(tenant_id=T, query_id=q2, asked_by=TECH, machine_id=HP07, note=None, assigned_to=None)
    open_ids = [str(r["id"]) for r in repo.list_escalations(T, status="open", assigned_to=None,
                                                            include_unassigned=False, limit=200)]
    assert open_ids.index(a) < open_ids.index(b)                       # oldest open first
    mine = [str(r["id"]) for r in repo.list_escalations(T, status="open", assigned_to=EXPERT,
                                                        include_unassigned=True, limit=200)]
    assert a in mine and b in mine
    only = [str(r["id"]) for r in repo.list_escalations(T, status="open", assigned_to=EXPERT,
                                                        include_unassigned=False, limit=200)]
    assert a in only and b not in only
    every = repo.list_escalations(T, status=None, assigned_to=None, include_unassigned=False, limit=200)
    statuses = [r["status"] for r in every]
    assert statuses == sorted(statuses, key=["open", "answered", "closed"].index)
    assert repo.list_escalations(T2, status=None, assigned_to=None, include_unassigned=False, limit=10) == []


def test_close_open_for_query(repo):
    qid = new_query(repo)
    eid = repo.create_escalation(tenant_id=T, query_id=qid, asked_by=TECH, machine_id=HP07, note=None, assigned_to=None)
    assert repo.close_open_for_query(T, qid, "fixed_by_technician")
    assert repo.get_escalation(T, eid)["close_reason"] == "fixed_by_technician"


def test_people(repo):
    ex = repo.experts(T)
    assert [r["name"] for r in ex] == ["Anil Deshmukh", "Ramesh Patil", "Suresh Kulkarni"]
    assert next(r for r in ex if r["name"] == "Anil Deshmukh")["approved_records"] == 1
    assert repo.user_in_tenant(T, EXPERT)["role"] == "expert"
    assert repo.user_in_tenant(T2, EXPERT) is None


def test_sources(repo):
    rec = repo.record_source(T, R_APPROVED)
    assert rec["status"] == "approved" and rec["machine_code"] == "HP-02" and rec["author_name"] == "Anil Deshmukh"
    assert repo.record_source(T2, R_APPROVED) is None
    doc = repo.manual_page(T, DOC, 3)
    assert doc["title"] == "HPX-200 Service Manual" and [c["text"] for c in doc["chunks"]] == [
        "Pressure not building", "Check relief valve 210 bar"]
    assert len(repo.manual_page(T, DOC, None)["chunks"]) == 3
    assert repo.manual_page(T2, DOC, 3) is None
    log = repo.log_source(T, LOG)
    assert log["machine_code"] == "HP-07" and log["downtime_min"] == 150
    assert repo.log_source(T2, LOG) is None


def test_realtime_publication(repo):
    rows = sql(repo, "select tablename from pg_publication_tables where pubname = 'supabase_realtime' order by 1")
    assert [r[0] for r in rows] == ["escalations", "repair_records"]
