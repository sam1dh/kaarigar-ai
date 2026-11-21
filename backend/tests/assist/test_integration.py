"""Real Supabase + Groq (no Sarvam). Run inside the repo after Phase 1 seeding:

    pytest -m integration tests/assist/test_integration.py

Asks two typed questions through the real pipeline (Phase 1 search + Groq) and checks the saved rows.
Cleans up its own rows. ~3 Groq calls.
"""
import os
import uuid

import pytest

pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not (os.environ.get("DATABASE_URL") and os.environ.get("GROQ_API_KEY")),
                                 reason="needs DATABASE_URL and GROQ_API_KEY")]


@pytest.fixture(scope="module")
def ctx():
    from app.assist import adapters
    from app.assist.service import init_assist, shutdown_assist
    from app.services import embeddings

    # This suite runs outside the API process, so nothing has loaded Phase 1's
    # embedding model yet; without it hybrid search returns embed_not_ready.
    embeddings.start_loading()
    embeddings.wait_ready(180)
    svc = init_assist()
    with adapters.db_conn() as conn:
        row = conn.execute("select u.id, u.tenant_id from users u where u.employee_id = 'SH-0412'").fetchone()
    assert row, "seed user Amit SH-0412 not found (run Phase 0 seed)"
    user_id, tenant_id = (row["id"], row["tenant_id"]) if isinstance(row, dict) else row
    created: list[str] = []
    yield svc, str(user_id), str(tenant_id), created
    with adapters.db_conn() as conn:
        for qid in created:
            conn.execute("delete from queries where id = %s", (qid,))
        conn.commit()
    shutdown_assist()


def _ask(svc, user_id, tenant_id, created, text, machine_code, language):
    from app.assist.pipeline import AskRequest

    machine = svc.repo.machine_by_code(tenant_id, machine_code)
    qid = str(uuid.uuid4())
    svc.repo.create_query(query_id=qid, tenant_id=tenant_id, user_id=user_id, machine_id=str(machine["id"]),
                          language=language, input_mode="text", audio_path=None, question_original=text)
    created.append(qid)
    events = []
    status = svc.pipeline.run(AskRequest(query_id=qid, tenant_id=tenant_id, user_id=user_id, language=language,
                                         machine=machine, text=text), lambda e, d: events.append((e, d)))
    return qid, status, events


def test_english_question_is_answered_with_citations(ctx):
    svc, user_id, tenant_id, created = ctx
    qid, status, events = _ask(svc, user_id, tenant_id, created, "HP-07 pressure is not building up", "HP-07", "en-IN")
    assert status == "answered", events[-1]
    row = svc.repo.get_query(tenant_id, qid)
    assert row["answer_parts"]["refs_used"]
    assert any(c.get("seed_key") in ("R01", "R09") or c["source_type"] == "manual" for c in row["citations"])
    assert row["first_token_ms"] and row["first_token_ms"] < 8000


def test_hindi_question_is_answered_in_hindi(ctx):
    svc, user_id, tenant_id, created = ctx
    qid, status, _ = _ask(svc, user_id, tenant_id, created, "HP-07 में प्रेशर नहीं बन रहा", "HP-07", "hi-IN")
    assert status == "answered"
    row = svc.repo.get_query(tenant_id, qid)
    assert any("ऀ" <= ch <= "ॿ" for ch in row["answer_local"])     # Devanagari in the answer
    assert row["question_en"] and row["question_en"].isascii()
