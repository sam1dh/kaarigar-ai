"""Capture graph flows with fakes + LangGraph's in-memory checkpointer."""
import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.capture.errors import CaptureError
from app.capture.runner import CaptureRunner, NotWaiting
from app.capture.schemas import AICheck, Extraction

from .fakes import EXPERT, MACHINE, SUPERVISOR, TENANT, FakeLLM, FakeSTT, make_deps


def new_record(repo, language="mr-IN", audio=True, transcript=None):
    rid = str(uuid.uuid4())
    repo.create_record(record_id=rid, tenant_id=TENANT, machine_id=MACHINE["id"], author_id=EXPERT,
                       language=language, audio_path=f"{TENANT}/{rid}.webm" if audio else None,
                       transcript_en=transcript)
    return rid


def runner_for(**kw):
    deps, spies = make_deps(**kw)
    return CaptureRunner(deps, InMemorySaver()), spies


def rec(spies, rid):
    return spies["repo"].records.get(rid)


# ---------------------------------------------------------------- happy path

def test_full_flow_marathi_expert_approved(fake_audio):
    r, spies = runner_for()
    rid = new_record(spies["repo"])
    r.run_sync(rid, TENANT)

    x = rec(spies, rid)
    assert x["status"] == "expert_review" and x["stage"] == "ready" and x["error"] is None
    assert x["audio_seconds"] == 42.5 and x["transcript_en"].startswith("Pressure")
    assert x["fields"]["symptom"] == "Pressure not building up"
    assert x["fields"]["stt"]["segments"] == 2
    # existing symptom reused, cause/fix suggested as new
    assert x["fields"]["links"]["symptom"]["id"] == "sym-press"
    assert x["fields"]["links"]["cause"]["new"] is True
    assert x["symptom_id"] == "sym-press"
    # AI check ran with manual context; translated for Marathi
    assert x["ai_check"]["safety_ok"] is True and x["ai_check"]["manual_sources"]
    assert x["fields_local"]["symptom"].startswith("[mr] ")
    assert x["fields_local"]["language"] == "mr-IN"
    assert r.next_nodes(rid) == ("expert_review",)
    assert [c[0] for c in spies["llm"].calls] == ["repair_record", "ai_check", "translation"]
    # models: extraction small, check large
    assert spies["llm"].calls[0][1] == "openai/gpt-oss-20b" and spies["llm"].calls[1][1] == "openai/gpt-oss-120b"

    # expert edits the fix in Marathi -> translated back to English
    r.submit_expert(rid, {"action": "submit", "edits": {"fix": "रिलीफ व्हॉल्व्ह 210 bar"}, "edit_language": "mr-IN"})
    x = rec(spies, rid)
    assert x["status"] == "pending" and x["submitted_at"] is not None and x["edited_by_expert"] is True
    assert x["fields"]["fix"] == "EN:रिलीफ व्हॉल्व्ह 210 bar"
    assert x["fields_local"]["fix"] == "रिलीफ व्हॉल्व्ह 210 bar"      # expert still sees what they typed
    assert r.next_nodes(rid) == ("supervisor_review",)

    # supervisor approves with an English edit
    r.review(rid, {"action": "approve", "edits": {"safety_note": "Lower ram on blocks and release pressure."},
                   "reviewer_id": SUPERVISOR})
    x = rec(spies, rid)
    assert x["status"] == "approved" and x["reviewed_by"] == SUPERVISOR and x["edited_by_reviewer"] is True
    assert x["safety_note"] == "Lower ram on blocks and release pressure."
    assert x["symptom_id"] == "sym-press" and x["cause_id"] and x["fix_id"]
    assert spies["rebuild"].calls == [(rid,)]
    assert r.next_nodes(rid) == ()
    # the new phrasing became an alias of the existing symptom
    assert "pressure not building up" in spies["repo"].taxonomy["symptom"]["sym-press"]["aliases"]


def test_english_expert_skips_translation(fake_audio):
    r, spies = runner_for()
    rid = new_record(spies["repo"], language="en-IN")
    r.run_sync(rid, TENANT)
    x = rec(spies, rid)
    assert x["fields_local"] is None
    assert "translation" not in [c[0] for c in spies["llm"].calls]
    r.submit_expert(rid, {"action": "submit", "edits": {"cause": "lock nut loose"}, "edit_language": "en-IN"})
    assert rec(spies, rid)["fields"]["cause"] == "lock nut loose"
    assert "translation" not in [c[0] for c in spies["llm"].calls]


def test_submit_without_edits(fake_audio):
    r, spies = runner_for()
    rid = new_record(spies["repo"])
    r.run_sync(rid, TENANT)
    n_calls = len(spies["llm"].calls)
    r.submit_expert(rid, {"action": "submit", "edits": {}, "edit_language": "mr-IN"})
    x = rec(spies, rid)
    assert x["status"] == "pending" and x["edited_by_expert"] is False
    assert len(spies["llm"].calls) == n_calls        # no back-translation call


def test_text_mode_skips_speech(fake_audio):
    r, spies = runner_for()
    rid = new_record(spies["repo"], audio=False, transcript="The pump made thak-thak noise, oil was low, topped up.")
    r.run_sync(rid, TENANT)
    assert spies["stt"].calls == 0 and fake_audio == []
    assert rec(spies, rid)["status"] == "expert_review"


# ---------------------------------------------------------------- reject / discard

def test_reject_removes_from_search(fake_audio):
    r, spies = runner_for()
    rid = new_record(spies["repo"])
    r.run_sync(rid, TENANT)
    r.submit_expert(rid, {"action": "submit", "edits": {}, "edit_language": "mr-IN"})
    r.review(rid, {"action": "reject", "reason": "Cause is not clear, record again.", "reviewer_id": SUPERVISOR})
    x = rec(spies, rid)
    assert x["status"] == "rejected" and x["reject_reason"] == "Cause is not clear, record again."
    assert spies["rebuild"].calls == [(rid,)]


def test_discard_at_expert_check_deletes_record_and_audio(fake_audio):
    r, spies = runner_for()
    rid = new_record(spies["repo"])
    audio_path = rec(spies, rid)["audio_path"]
    r.run_sync(rid, TENANT)
    r.discard(rid, TENANT)
    assert rid not in spies["repo"].records
    assert spies["delete_audio"].calls == [(audio_path,)]


def test_discard_after_failure_before_check(fake_audio):
    r, spies = runner_for(stt=FakeSTT(fail_times=5))
    rid = new_record(spies["repo"])
    r.run_sync(rid, TENANT)
    assert rec(spies, rid)["stage"] == "failed"
    r.discard(rid, TENANT)
    assert rid not in spies["repo"].records and spies["delete_audio"].calls


# ---------------------------------------------------------------- failures & retry

def test_stt_failure_then_retry_continues(fake_audio):
    r, spies = runner_for(stt=FakeSTT(fail_times=1))
    rid = new_record(spies["repo"])
    r.run_sync(rid, TENANT)
    x = rec(spies, rid)
    assert x["stage"] == "failed" and x["error"] == "stt_failed" and x["status"] == "draft"
    r.retry(rid, TENANT).result(timeout=10)
    x = rec(spies, rid)
    assert x["status"] == "expert_review" and x["stage"] == "ready" and x["error"] is None
    assert spies["stt"].calls == 2


def test_llm_failure_in_check_retries_only_from_check(fake_audio):
    llm = FakeLLM(fail_on={"ai_check"})
    r, spies = runner_for(llm=llm)
    rid = new_record(spies["repo"])
    r.run_sync(rid, TENANT)
    assert rec(spies, rid)["error"] == "llm_failed"
    r.retry(rid, TENANT).result(timeout=10)
    names = [c[0] for c in llm.calls]
    assert names.count("repair_record") == 1          # extraction not repeated
    assert names.count("ai_check") == 2
    assert spies["stt"].calls == 1
    assert rec(spies, rid)["status"] == "expert_review"


def test_no_speech_is_not_retryable(fake_audio):
    r, spies = runner_for(stt=FakeSTT(transcript="hmm ok"))
    rid = new_record(spies["repo"])
    r.run_sync(rid, TENANT)
    x = rec(spies, rid)
    assert x["stage"] == "failed" and x["error"] == "no_speech"


def test_translation_failure_shows_english_instead_of_blocking(fake_audio):
    r, spies = runner_for(llm=FakeLLM(translate_fail=True))
    rid = new_record(spies["repo"])
    r.run_sync(rid, TENANT)
    x = rec(spies, rid)
    assert x["status"] == "expert_review" and x["fields_local"] is None


def test_failed_back_translation_can_be_resent(fake_audio):
    llm = FakeLLM()
    r, spies = runner_for(llm=llm)
    rid = new_record(spies["repo"])
    r.run_sync(rid, TENANT)
    llm.translate_fail = True
    with pytest.raises(CaptureError):
        r.submit_expert(rid, {"action": "submit", "edits": {"fix": "नवीन"}, "edit_language": "mr-IN"})
    assert rec(spies, rid)["status"] == "expert_review"
    assert r.next_nodes(rid) == ("apply_expert",)
    llm.translate_fail = False
    r.submit_expert(rid, {"action": "submit", "edits": {"fix": "नवीन fix"}, "edit_language": "mr-IN"})
    assert rec(spies, rid)["fields"]["fix"] == "EN:नवीन fix"


def test_not_a_repair_note_gets_high_issue(fake_audio):
    ext = Extraction(is_repair_note=False, missing=["symptom", "cause", "fix", "steps", "safety_note"])
    r, spies = runner_for(llm=FakeLLM(extraction=ext, check=AICheck(issues=[], safety_ok=True, summary="-")))
    rid = new_record(spies["repo"], language="en-IN")
    r.run_sync(rid, TENANT)
    issues = rec(spies, rid)["ai_check"]["issues"]
    assert issues[0]["field"] == "general" and issues[0]["severity"] == "high"


# ---------------------------------------------------------------- guards

def test_review_before_expert_submit_is_refused(fake_audio):
    r, spies = runner_for()
    rid = new_record(spies["repo"])
    r.run_sync(rid, TENANT)
    with pytest.raises(NotWaiting):
        r.review(rid, {"action": "approve", "edits": {}, "reviewer_id": SUPERVISOR})


def test_double_submit_is_refused(fake_audio):
    r, spies = runner_for()
    rid = new_record(spies["repo"])
    r.run_sync(rid, TENANT)
    r.submit_expert(rid, {"action": "submit", "edits": {}, "edit_language": "mr-IN"})
    with pytest.raises(NotWaiting):
        r.submit_expert(rid, {"action": "submit", "edits": {}, "edit_language": "mr-IN"})


def test_double_approve_is_refused(fake_audio):
    r, spies = runner_for()
    rid = new_record(spies["repo"])
    r.run_sync(rid, TENANT)
    r.submit_expert(rid, {"action": "submit", "edits": {}, "edit_language": "mr-IN"})
    r.review(rid, {"action": "approve", "edits": {}, "reviewer_id": SUPERVISOR})
    with pytest.raises(NotWaiting):
        r.review(rid, {"action": "approve", "edits": {}, "reviewer_id": SUPERVISOR})
    assert spies["rebuild"].calls == [(rid,)]


def test_restart_recovery_marks_stuck_records():
    deps, spies = make_deps()
    rid = new_record(spies["repo"])
    spies["repo"].records[rid]["stage"] = "extracting"
    assert spies["repo"].mark_stuck_failed("server_restarted") == 1
    assert spies["repo"].records[rid]["error"] == "server_restarted"
