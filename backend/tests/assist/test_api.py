"""HTTP tests for /assist, /expert and /manager/escalations (no Supabase, Sarvam or Groq)."""
import json
import types
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.assist import adapters
from app.assist.adapters import AssistUser
from app.assist.router_assist import router as assist_router
from app.assist.router_escalations import expert_router, manager_router
from app.assist.service import get_service

from .fakes import (DOC_HPX, EXPERT, EXPERT2, HP07, LOG_1, OTHER_SUP, OTHER_TENANT, REC_DRAFT, REC_R01, SUPERVISOR,
                    TECH, TECH2, TENANT, FakeSearch, FakeWriter, make_service)

USERS = {
    "tech": AssistUser(TECH, TENANT, "technician", False, "hi-IN", "Amit Kale"),
    "tech2": AssistUser(TECH2, TENANT, "technician", False, "ta-IN", "Karthik Raman"),
    "expert": AssistUser(EXPERT, TENANT, "expert", False, "mr-IN", "Ramesh Patil"),
    "expert2": AssistUser(EXPERT2, TENANT, "expert", False, "hi-IN", "Anil Deshmukh"),
    "sup": AssistUser(SUPERVISOR, TENANT, "supervisor", True, "hi-IN", "Suresh Kulkarni"),
    "other_sup": AssistUser(OTHER_SUP, OTHER_TENANT, "supervisor", True, "en-IN", "Elsewhere"),
}


def build(**kw):
    svc, spies = make_service(**kw)
    state = {"user": USERS["tech"]}
    app = FastAPI()
    app.include_router(assist_router)
    app.include_router(expert_router)
    app.include_router(manager_router)
    app.dependency_overrides[adapters.assist_user] = lambda: state["user"]
    app.dependency_overrides[get_service] = lambda: svc
    client = TestClient(app)

    def as_(who):
        state["user"] = USERS[who]
        return client

    return types.SimpleNamespace(client=client, as_=as_, spies=spies, svc=svc, repo=spies["repo"])


@pytest.fixture
def env():
    e = build()
    yield e
    e.svc.shutdown()


def code(resp):
    return resp.json()["detail"]["error"]["code"]


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    events = []
    for frame in raw.split("\n\n"):
        if not frame.strip() or frame.startswith(":"):
            continue
        ev, data = None, None
        for line in frame.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        events.append((ev, data))
    return events


def ask(env, who="tech", **form):
    files = None
    if "audio" in form:
        files = {"audio": form.pop("audio")}
    with env.as_(who).stream("POST", "/assist/ask", data=form, files=files) as r:
        body = "".join(r.iter_text())
        return r, (parse_sse(body) if r.status_code == 200 else body)


def ask_ok(env, who="tech", text="HP-07 में प्रेशर नहीं बन रहा", machine_code="HP-07"):
    r, events = ask(env, who, text=text, machine_code=machine_code)
    assert r.status_code == 200, events
    done = [d for e, d in events if e == "done"]
    assert done, events
    return done[0]["query_id"], events


# ============================================================================ ask

def test_ask_streams_events_in_order(env):
    r, events = ask(env, text="HP-07 में प्रेशर नहीं बन रहा", machine_code="hp-07")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"].startswith("no-cache")
    names = [e for e, _ in events]
    assert names[:2] == ["meta", "stage"]
    assert names.index("question") < names.index("sources") < names.index("delta") < names.index("done")
    meta = events[0][1]
    assert meta["machine"]["code"] == "HP-07"
    qid = meta["query_id"]
    answer = "".join(d["text"] for e, d in events if e == "delta")
    assert answer.startswith("SAFETY:") and "[E1]" in answer
    row = env.repo.queries[qid]
    assert row["status"] == "answered" and row["input_mode"] == "text" and row["user_id"] == TECH


def test_ask_voice_stores_recording(env):
    r, events = ask(env, audio=("q.webm", b"\x1aE\xdf\xa3" + b"0" * 2000, "audio/webm"), machine_code="HP-07")
    assert r.status_code == 200
    qid = events[0][1]["query_id"]
    row = env.repo.queries[qid]
    assert row["input_mode"] == "voice" and row["audio_path"] == f"{TENANT}/questions/{qid}.webm"
    assert ("audio", row["audio_path"]) in env.spies["storage"].files
    assert row["question_original"].startswith("HP-07")


def test_ask_voice_storage_failure_still_answers(env):
    env.spies["storage"].fail_upload = True
    r, events = ask(env, audio=("q.webm", b"0" * 2000, "audio/webm"))
    assert r.status_code == 200 and any(e == "done" for e, _ in events)
    assert env.repo.queries[events[0][1]["query_id"]]["audio_path"] is None


@pytest.mark.parametrize("form,files,status,err", [
    ({}, None, 422, "question_required"),
    ({"text": "hi"}, None, 422, "bad_question"),
    ({"text": "x" * 501}, None, 422, "bad_question"),
    ({"text": "pressure low", "machine_code": "ZZ-99"}, None, 404, "machine_not_found"),
    ({}, {"audio": ("q.txt", b"0" * 2000, "text/plain")}, 415, "unsupported_audio"),
    ({}, {"audio": ("q.webm", b"0" * 100, "audio/webm")}, 422, "audio_empty"),
    ({"text": "pressure"}, {"audio": ("q.webm", b"0" * 2000, "audio/webm")}, 422, "question_required"),
])
def test_ask_validation(env, form, files, status, err):
    r = env.as_("tech").post("/assist/ask", data=form, files=files)
    assert r.status_code == status and code(r) == err


def test_ask_audio_too_big(env):
    big = b"0" * (5 * 1024 * 1024 + 10)
    r = env.as_("tech").post("/assist/ask", files={"audio": ("q.webm", big, "audio/webm")})
    assert r.status_code == 413 and code(r) == "audio_too_big"


def test_ask_rate_limit():
    e = build(ASK_PER_MINUTE=2)
    try:
        ask_ok(e)
        ask_ok(e)
        r = e.as_("tech").post("/assist/ask", data={"text": "pressure low"})
        assert r.status_code == 429 and code(r) == "rate_limited"
        ask_ok(e, who="tech2")              # per person
    finally:
        e.svc.shutdown()


def test_ask_failure_arrives_as_error_event():
    e = build(writer=FakeWriter(fail_before=True))
    try:
        r, events = ask(e, text="pressure low", machine_code="HP-07")
        assert r.status_code == 200
        err = [d for ev, d in events if ev == "error"][0]
        assert err["code"] == "llm_failed" and err["query_id"]
        assert e.repo.queries[err["query_id"]]["status"] == "failed"
    finally:
        e.svc.shutdown()


def test_ask_other_plant_machine_is_not_found(env):
    r = env.as_("other_sup").post("/assist/ask", data={"text": "pressure low", "machine_code": "HP-07"})
    assert r.status_code == 404


# ============================================================================ my questions

def test_list_and_get_my_questions(env):
    qid, _ = ask_ok(env)
    ask_ok(env, who="tech2", text="pump noise")
    items = env.as_("tech").get("/assist/queries").json()["items"]
    assert [i["id"] for i in items] == [qid]
    assert items[0]["first_step"] and items[0]["machine"]["code"] == "HP-07"
    v = env.as_("tech").get(f"/assist/queries/{qid}").json()
    assert v["status"] == "answered" and v["answer"]["parts"]["steps"]
    assert v["can"] == {"feedback": True, "escalate": True, "read_aloud": True}
    assert v["sources"][0]["ref"] == "E1"


def test_question_visibility(env):
    qid, _ = ask_ok(env)
    assert env.as_("tech2").get(f"/assist/queries/{qid}").status_code == 404
    assert env.as_("expert").get(f"/assist/queries/{qid}").status_code == 404      # not escalated
    assert env.as_("sup").get(f"/assist/queries/{qid}").status_code == 200
    assert env.as_("other_sup").get(f"/assist/queries/{qid}").status_code == 404
    assert env.as_("tech").get("/assist/queries/not-a-uuid").status_code == 422


def test_feedback(env):
    qid, _ = ask_ok(env)
    r = env.as_("tech").post(f"/assist/queries/{qid}/feedback", json={"outcome": "not_fixed"})
    assert r.status_code == 200 and r.json()["feedback"] == "not_fixed"
    r = env.as_("tech").post(f"/assist/queries/{qid}/feedback", json={"outcome": "fixed"})
    assert r.json()["feedback"] == "fixed"                                  # changed, one row
    assert len([k for k in env.repo.feedback if k[0] == qid]) == 1
    assert env.as_("tech").post(f"/assist/queries/{qid}/feedback", json={"outcome": "great"}).status_code == 422
    assert env.as_("sup").post(f"/assist/queries/{qid}/feedback", json={"outcome": "fixed"}).status_code == 403


def test_feedback_needs_a_finished_answer(env):
    qid = str(uuid.uuid4())
    env.repo.create_query(query_id=qid, tenant_id=TENANT, user_id=TECH, machine_id=HP07["id"], language="hi-IN",
                          input_mode="text", audio_path=None, question_original="x")
    r = env.as_("tech").post(f"/assist/queries/{qid}/feedback", json={"outcome": "fixed"})
    assert r.status_code == 409 and code(r) == "not_answered"


def test_read_aloud_generates_once_then_uses_cache(env):
    qid, _ = ask_ok(env)
    r = env.as_("tech").post(f"/assist/queries/{qid}/tts")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content.startswith(b"RIFF")
    text, lang = env.spies["tts"].calls[0]
    assert lang == "hi-IN" and "[" not in text and text.startswith("Safety.")
    r2 = env.as_("tech").post(f"/assist/queries/{qid}/tts")
    assert r2.status_code == 200 and len(env.spies["tts"].calls) == 1
    assert env.as_("tech2").post(f"/assist/queries/{qid}/tts").status_code == 404


def test_read_aloud_only_for_answers():
    e = build(search=FakeSearch(results=[]))
    try:
        qid, _ = ask_ok(e, text="forklift brakes")
        r = e.as_("tech").post(f"/assist/queries/{qid}/tts")
        assert r.status_code == 409
    finally:
        e.svc.shutdown()


def test_read_aloud_service_down(env):
    qid, _ = ask_ok(env)
    env.spies["tts"].fail = True
    r = env.as_("tech").post(f"/assist/queries/{qid}/tts")
    assert r.status_code == 503 and code(r) == "tts_failed"


# ============================================================================ sources

def test_record_source_translated_for_the_viewer(env):
    r = env.as_("tech").get(f"/assist/sources/record/{REC_R01}")
    assert r.status_code == 200
    v = r.json()
    assert v["type"] == "record" and v["author"]["name"] == "Ramesh Patil" and v["approved_by"] == "Suresh Kulkarni"
    assert v["fields"]["fix"] == "reset relief valve to 210 bar"
    assert v["local"]["fix"].startswith("[local]") and v["audio_url"].startswith("https://signed/audio/")
    assert env.as_("tech").get(f"/assist/sources/record/{REC_R01}?translate=false").json()["local"] is None


def test_unapproved_records_are_not_sources_for_technicians(env):
    assert env.as_("tech").get(f"/assist/sources/record/{REC_DRAFT}").status_code == 404
    assert env.as_("expert2").get(f"/assist/sources/record/{REC_DRAFT}").status_code == 200   # author
    assert env.as_("sup").get(f"/assist/sources/record/{REC_DRAFT}").status_code == 200
    assert env.as_("other_sup").get(f"/assist/sources/record/{REC_R01}").status_code == 404


def test_manual_and_log_sources(env):
    v = env.as_("tech").get(f"/assist/sources/manual/{DOC_HPX}?page=3").json()
    assert v["title"] == "HPX-200 Service Manual" and v["page"] == 3
    assert [s["page"] for s in v["sections"]] == [3]
    assert v["pdf_url"].endswith("#page=3")
    log = env.as_("tech").get(f"/assist/sources/log/{LOG_1}").json()
    assert log["fault"] == "pressure low" and log["downtime_min"] == 150 and log["machine"]["code"] == "HP-07"
    assert env.as_("other_sup").get(f"/assist/sources/log/{LOG_1}").status_code == 404
    assert env.as_("tech").get("/assist/sources/manual/xyz").status_code == 422


def test_machine_lookup_by_qr_and_code(env):
    assert env.as_("tech").get(f"/assist/machines/qr/{HP07['qr_token']}").json()["code"] == "HP-07"
    assert env.as_("tech").get("/assist/machines/qr/notatoken!").status_code == 404
    assert env.as_("tech").get("/assist/machines/qr/abcdef0123456789").status_code == 404
    assert env.as_("other_sup").get(f"/assist/machines/qr/{HP07['qr_token']}").status_code == 404
    assert env.as_("tech").get("/assist/machines/hp-07").json()["model"] == "HPX-200"


# ============================================================================ escalation flow

def escalate(env, who="tech", note=None, **ask_kw):
    qid, _ = ask_ok(env, who=who, **ask_kw)
    r = env.as_(who).post(f"/assist/queries/{qid}/escalate", json={"note": note})
    assert r.status_code == 201, r.text
    return qid, r.json()


def test_escalate_picks_the_expert_who_fixed_this_machine(env):
    qid, res = escalate(env, note="  already changed the   filter ")
    assert res["assigned_to"]["name"] == "Ramesh Patil"          # wrote the approved HP-07 record
    e = env.repo.escalations[res["escalation_id"]]
    assert e["note"] == "already changed the filter" and e["machine_id"] == HP07["id"]
    assert env.repo.queries[qid]["escalated"] is True
    v = env.as_("tech").get(f"/assist/queries/{qid}").json()
    assert v["escalation"]["status"] == "open" and v["can"]["escalate"] is False
    again = env.as_("tech").post(f"/assist/queries/{qid}/escalate", json={})
    assert again.status_code == 409 and code(again) == "already_escalated"


def test_escalate_rules(env):
    qid, _ = ask_ok(env)
    assert env.as_("tech2").post(f"/assist/queries/{qid}/escalate", json={}).status_code == 404
    assert env.as_("sup").post(f"/assist/queries/{qid}/escalate", json={}).status_code == 403
    assert env.as_("tech").post(f"/assist/queries/{qid}/escalate", json={"note": "x" * 501}).status_code == 422


def test_failed_question_can_still_be_escalated():
    e = build(writer=FakeWriter(fail_before=True))
    try:
        r, events = ask(e, text="pressure low", machine_code="HP-07")
        qid = events[0][1]["query_id"]
        assert e.as_("tech").post(f"/assist/queries/{qid}/escalate", json={}).status_code == 201
    finally:
        e.svc.shutdown()


def test_expert_inbox_and_visibility(env):
    qid, res = escalate(env)
    eid = res["escalation_id"]
    inbox = env.as_("expert").get("/expert/escalations").json()["items"]
    assert [i["id"] for i in inbox] == [eid] and inbox[0]["asked_by"]["name"] == "Amit Kale"
    assert env.as_("expert").get("/expert/escalations/count").json() == {"mine": 1, "unassigned": 0}
    assert env.as_("expert2").get("/expert/escalations").json()["items"] == []
    assert env.as_("expert2").get(f"/expert/escalations/{eid}").status_code == 404
    v = env.as_("expert").get(f"/expert/escalations/{eid}").json()
    assert v["kaarigar"]["status"] == "answered" and v["kaarigar"]["parts"]["steps"]
    assert v["question"]["en"] == "pressure is not building on HP-07"
    # the assigned expert can open the original question too
    assert env.as_("expert").get(f"/assist/queries/{qid}").status_code == 200
    assert env.as_("tech").get("/expert/escalations").status_code == 403


def test_unassigned_question_can_be_taken(env):
    _, res = escalate(env)
    eid = res["escalation_id"]
    env.repo.escalations[eid]["assigned_to"] = None
    assert env.as_("expert2").get("/expert/escalations").json()["items"][0]["id"] == eid
    r = env.as_("expert2").post(f"/expert/escalations/{eid}/take")
    assert r.status_code == 200 and r.json()["assigned_to"]["name"] == "Anil Deshmukh"
    r = env.as_("expert").post(f"/expert/escalations/{eid}/take")
    assert r.status_code == 409 and code(r) == "assigned_to_other"


def test_quick_text_reply_reaches_the_technician_in_their_language(env):
    qid, res = escalate(env)
    eid = res["escalation_id"]
    r = env.as_("expert").post(f"/expert/escalations/{eid}/reply-text", json={"text": "Check fuse F3, coming in 10 min"})
    assert r.status_code == 200 and r.json()["status"] == "answered"
    v = env.as_("tech").get(f"/assist/queries/{qid}").json()
    esc = v["escalation"]
    assert esc["status"] == "answered" and esc["replied_by"]["name"] == "Ramesh Patil"
    assert esc["reply"]["text"] == "Check fuse F3, coming in 10 min"
    assert esc["reply"]["local"]["text"].startswith("EN| ")       # FakeWriter.text stands in for translation
    assert env.repo.escalations[eid]["reply_local"]["language"] == "hi-IN"    # cached
    again = env.as_("expert").post(f"/expert/escalations/{eid}/reply-text", json={"text": "more"})
    assert again.status_code == 409


def test_voice_reply_becomes_a_capture_record_and_answers_on_send(env):
    qid, res = escalate(env)
    eid = res["escalation_id"]
    r = env.as_("expert").post(f"/expert/escalations/{eid}/reply",
                               files={"audio": ("r.webm", b"0" * 5000, "audio/webm")})
    assert r.status_code == 202
    rid = r.json()["record_id"]
    call = env.spies["starter"].calls[0]
    assert call["escalation_id"] == eid and call["author_id"] == EXPERT and call["machine_id"] == HP07["id"]
    assert call["audio_path"] == f"{TENANT}/{rid}.webm" and call["language"] == "mr-IN"
    rec = env.repo.records[rid]
    assert rec["source"] == "escalation" and rec["escalation_id"] == eid
    # still open while the expert checks the note; a second recording is refused
    item = env.as_("expert").get("/expert/escalations").json()["items"][0]
    assert item["reply_in_progress"] is True
    dup = env.as_("expert").post(f"/expert/escalations/{eid}/reply", files={"audio": ("r.webm", b"0" * 5000, "audio/webm")})
    assert dup.status_code == 409 and code(dup) == "reply_in_progress"
    # Phase 2: expert checks and sends -> status pending -> 0004 trigger marks the escalation answered
    rec["fields"] = {"symptom": "pressure not building", "fix": "reset relief valve", "steps": ["Set 210 bar"],
                     "cause": None, "safety_note": "Lower ram first"}
    env.repo.record_sent_to_supervisor(rid)
    v = env.as_("tech").get(f"/assist/queries/{qid}").json()["escalation"]
    assert v["status"] == "answered"
    assert v["reply"]["record"]["id"] == rid and v["reply"]["record"]["audio_url"]
    assert v["reply"]["local"]["fields"]["fix"] == "[local] reset relief valve"


def test_voice_reply_text_mode_is_dev_only():
    e = build(APP_ENV="production")
    try:
        _, res = escalate(e)
        r = e.as_("expert").post(f"/expert/escalations/{res['escalation_id']}/reply",
                                 data={"transcript_en": "Reset the relief valve to 210 bar with the gauge."})
        assert r.status_code == 403 and code(r) == "text_mode_disabled"
    finally:
        e.svc.shutdown()


def test_reply_rules(env):
    _, res = escalate(env)
    eid = res["escalation_id"]
    assert env.as_("expert2").post(f"/expert/escalations/{eid}/reply-text", json={"text": "hi there"}).status_code == 409
    assert env.as_("tech").post(f"/expert/escalations/{eid}/reply-text", json={"text": "hi there"}).status_code == 403
    assert env.as_("expert").post(f"/expert/escalations/{eid}/reply").status_code == 422
    assert env.as_("expert").post(f"/expert/escalations/{eid}/reply",
                                  files={"audio": ("r.txt", b"0" * 5000, "text/plain")}).status_code == 415
    # a supervisor may answer even when assigned to someone else
    assert env.as_("sup").post(f"/expert/escalations/{eid}/reply-text", json={"text": "I'll come"}).status_code == 200


def test_expert_cannot_answer_own_question(env):
    qid, _ = ask_ok(env, who="expert2", text="pump noise")
    r = env.as_("expert2").post(f"/assist/queries/{qid}/escalate", json={})
    eid = r.json()["escalation_id"]
    assert r.json()["assigned_to"]["name"] == "Ramesh Patil"
    env.repo.escalations[eid]["assigned_to"] = None
    assert env.as_("expert2").post(f"/expert/escalations/{eid}/take").status_code == 409


def test_technician_fixing_it_closes_the_open_escalation(env):
    qid, res = escalate(env)
    env.as_("tech").post(f"/assist/queries/{qid}/feedback", json={"outcome": "fixed"})
    e = env.repo.escalations[res["escalation_id"]]
    assert e["status"] == "closed" and e["close_reason"] == "fixed_by_technician"


# ============================================================================ manager (W2)

def test_manager_list_count_detail(env):
    _, a = escalate(env)
    _, b = escalate(env, who="tech2", text="pump noise")
    env.repo.escalations[b["escalation_id"]]["assigned_to"] = None
    r = env.as_("sup").get("/manager/escalations").json()
    assert {i["id"] for i in r["items"]} == {a["escalation_id"], b["escalation_id"]}
    assert r["counts"] == {"open": 2, "unassigned": 1}
    assert env.as_("sup").get("/manager/escalations/count").json() == {"open": 2, "unassigned": 1}
    d = env.as_("sup").get(f"/manager/escalations/{a['escalation_id']}").json()
    assert d["kaarigar"]["answer_en"] and d["machine"]["code"] == "HP-07"
    assert env.as_("tech").get("/manager/escalations").status_code == 403
    assert env.as_("expert").get("/manager/escalations").status_code == 403
    assert env.as_("other_sup").get(f"/manager/escalations/{a['escalation_id']}").status_code == 404
    assert env.as_("other_sup").get("/manager/escalations").json()["items"] == []


def test_manager_assign_and_close(env):
    _, res = escalate(env)
    eid = res["escalation_id"]
    r = env.as_("sup").post(f"/manager/escalations/{eid}/assign", json={"user_id": EXPERT2})
    assert r.status_code == 200 and r.json()["assigned_to"]["name"] == "Anil Deshmukh"
    bad = env.as_("sup").post(f"/manager/escalations/{eid}/assign", json={"user_id": TECH2})
    assert bad.status_code == 422 and code(bad) == "not_an_expert"
    asker = env.as_("sup").post(f"/manager/escalations/{eid}/assign", json={"user_id": TECH})
    assert asker.status_code == 422
    other = env.as_("sup").post(f"/manager/escalations/{eid}/assign", json={"user_id": OTHER_SUP})
    assert other.status_code == 422
    r = env.as_("sup").post(f"/manager/escalations/{eid}/close", json={"reason": "not_needed"})
    assert r.status_code == 200 and r.json()["status"] == "closed"
    assert env.as_("sup").post(f"/manager/escalations/{eid}/close", json={}).status_code == 409
    assert env.as_("sup").post(f"/manager/escalations/{eid}/assign", json={"user_id": EXPERT}).status_code == 409
    assert env.as_("sup").get("/manager/escalations?status=closed").json()["items"][0]["id"] == eid


def test_experts_list(env):
    items = env.as_("sup").get("/manager/experts").json()["items"]
    names = [i["name"] for i in items]
    assert names[:2] == ["Anil Deshmukh", "Ramesh Patil"] and "Suresh Kulkarni" in names
    ramesh = next(i for i in items if i["name"] == "Ramesh Patil")
    assert ramesh["approved_records"] == 1
