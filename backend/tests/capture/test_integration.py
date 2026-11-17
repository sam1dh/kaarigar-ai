"""End-to-end against the real dev Supabase project + Groq (text mode: no Sarvam credits used).

Run:  pytest -m integration tests/capture/test_integration.py
Needs: Phase 0 + 1 done (seed + seed_knowledge), 0003 migration, GROQ_API_KEY, DATABASE_URL.
Uses ~3 Groq calls. Cleans up after itself.
"""
import pytest

pytestmark = pytest.mark.integration

TRANSCRIPT = ("On HP-07 the ram was moving with jerks after we changed the rod seal yesterday. Air was trapped in the "
              "cylinder. I opened the two bleed screws at the top and ran the ram slowly up and down ten times in "
              "inching mode until clear oil came without bubbles, then closed the screws and topped up the oil. "
              "I worked from the side of the press and wore goggles because oil comes out with pressure. "
              "Downtime was about forty minutes.")


@pytest.fixture(scope="module")
def ctx():
    from psycopg.rows import dict_row

    from app.capture import adapters
    from app.capture.repo import PostgresRepo
    from app.capture.runner import init_capture, shutdown_capture
    from app.capture.settings import get_capture_settings

    s = get_capture_settings()
    if not (s.DATABASE_URL and s.GROQ_API_KEY):
        pytest.skip("needs DATABASE_URL and GROQ_API_KEY")
    from app.services import embeddings

    embeddings.start_loading()
    embeddings.wait_ready()
    runner = init_capture()
    repo = PostgresRepo(adapters.db_conn)
    with adapters.db_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select id from tenants where slug = 'shree'")
        tenant = str(cur.fetchone()["id"])
        cur.execute("select id, employee_id, role from users where tenant_id = %s", (tenant,))
        users = {r["employee_id"] or r["role"]: str(r["id"]) for r in cur.fetchall()}
    yield {"runner": runner, "repo": repo, "tenant": tenant, "expert": users["SH-0107"],
           "supervisor": users["supervisor"]}
    shutdown_capture()


def test_text_note_to_approved_and_searchable(ctx):
    import uuid

    runner, repo, t = ctx["runner"], ctx["repo"], ctx["tenant"]
    machine = repo.machine_by_code(t, "HP-07")
    rid = str(uuid.uuid4())
    repo.create_record(record_id=rid, tenant_id=t, machine_id=str(machine["id"]), author_id=ctx["expert"],
                       language="mr-IN", audio_path=None, transcript_en=TRANSCRIPT)
    try:
        runner.run_sync(rid, t)
        rec = repo.get(t, rid)
        assert rec["status"] == "expert_review", rec.get("error")
        f = rec["fields"]
        assert f["is_repair_note"] is True
        assert f["symptom"] and "jerk" in f["symptom"].lower()
        assert f["safety_note"]                          # goggles / side of press was said
        assert f["downtime_min"] in (40, None)
        assert rec["fields_local"] and rec["fields_local"]["language"] == "mr-IN"
        assert "issues" in rec["ai_check"]

        runner.submit_expert(rid, {"action": "submit", "edits": {}, "edit_language": "mr-IN"})
        assert repo.get(t, rid)["status"] == "pending"
        runner.review(rid, {"action": "approve", "edits": {}, "reviewer_id": ctx["supervisor"]})
        rec = repo.get(t, rid)
        assert rec["status"] == "approved" and rec["symptom_id"]

        from app.services.search import search  # Phase 1
        res = search(tenant_id=t, q="ram jerky after seal change", machine_code="HP-07", k=8)
        results = res["results"] if isinstance(res, dict) else res.results
        assert any(str(r["source_id"] if isinstance(r, dict) else r.source_id) == rid for r in results)
    finally:
        rec = repo.get(t, rid)
        if rec:
            repo.update(t, rid, status="rejected")
            from app.capture.adapters import rebuild_record_chunks
            rebuild_record_chunks(rid)
            repo.delete(t, rid)
        runner.forget(rid)
