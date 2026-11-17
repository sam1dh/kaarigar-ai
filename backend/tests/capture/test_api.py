"""HTTP-level tests for /capture and /manager review endpoints.

Runs without Supabase: the repo, storage and runner are replaced with fakes. If the real
app.core.* modules don't exist (running this pack on its own), tiny stubs are installed.
"""
import importlib
import sys
import time
import types
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from .fakes import EXPERT, MACHINE, OTHER_TENANT, SUPERVISOR, TECH, TENANT, make_deps


def _ensure_stub(name: str, **attrs):
    try:
        importlib.import_module(name)
    except Exception:  # noqa: BLE001
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod


_ensure_stub("app.core")
_ensure_stub("app.core.auth", get_current_user=lambda: None)

from app.capture import adapters, router_capture, router_review  # noqa: E402
from app.capture.adapters import CaptureUser  # noqa: E402
from app.capture.runner import CaptureRunner, get_runner  # noqa: E402
from app.capture.settings import CaptureSettings, get_capture_settings  # noqa: E402

USERS = {
    "expert": CaptureUser(EXPERT, TENANT, "expert", False, "mr-IN", "Ramesh Patil"),
    "supervisor": CaptureUser(SUPERVISOR, TENANT, "supervisor", True, "hi-IN", "Suresh Kulkarni"),
    "tech": CaptureUser(TECH, TENANT, "technician", False, "hi-IN", "Amit Kale"),
    "other_expert": CaptureUser(str(uuid.uuid4()), TENANT, "expert", False, "en-IN", "Other Expert"),
    "other_plant_sup": CaptureUser(str(uuid.uuid4()), OTHER_TENANT, "supervisor", True, "en-IN", "Elsewhere"),
}


@pytest.fixture
def env(fake_audio, monkeypatch):
    deps, spies = make_deps()
    runner = CaptureRunner(deps, InMemorySaver())
    state = {"user": USERS["expert"], "settings": CaptureSettings(_env_file=None, APP_ENV="development")}
    uploads = []
    monkeypatch.setattr(adapters, "storage_upload", lambda b, p, d, ct: uploads.append((b, p, len(d), ct)))
    monkeypatch.setattr(adapters, "storage_signed_url", lambda b, p, e=3600: f"https://signed/{p}")

    app = FastAPI()
    try:
        from app.core.errors import install_error_handlers
    except ImportError:  # standalone pack without Phase 0
        pass
    else:
        install_error_handlers(app)
    app.include_router(router_capture.router)
    app.include_router(router_review.router)
    app.dependency_overrides[adapters.capture_user] = lambda: state["user"]
    app.dependency_overrides[router_capture.get_repo] = lambda: spies["repo"]
    app.dependency_overrides[get_runner] = lambda: runner
    app.dependency_overrides[get_capture_settings] = lambda: state["settings"]
    client = TestClient(app)

    def as_(who):
        state["user"] = USERS[who]
        return client

    yield types.SimpleNamespace(client=client, as_=as_, spies=spies, runner=runner, state=state, uploads=uploads)
    runner.shutdown()


def code(resp):
    return resp.json()["error"]["code"]


def wait_ready(env, rid, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = env.client.get(f"/capture/records/{rid}").json()
        if not r["processing"]:
            return r
        time.sleep(0.05)
    raise AssertionError("still processing")


AUDIO = ("note.webm", b"\x1aE\xdf\xa3" + b"0" * 4000, "audio/webm;codecs=opus")


def create(env, files=None, data=None):
    return env.client.post("/capture/records", data=data or {"machine_code": "HP-07"},
                           files=files if files is not None else {"audio": AUDIO})


# ------------------------------------------------------------------ create

def test_expert_records_and_gets_check_screen(env):
    r = create(env)
    assert r.status_code == 202
    rid = r.json()["record_id"]
    bucket, path, size, ctype = env.uploads[0]
    assert bucket == "audio" and path == f"{TENANT}/{rid}.webm" and ctype.startswith("audio/webm")
    view = wait_ready(env, rid)
    assert view["status"] == "expert_review" and view["can"]["submit"] is True
    assert view["machine"]["code"] == "HP-07" and view["language"] == "mr-IN"
    assert view["audio_url"] == f"https://signed/{TENANT}/{rid}.webm"
    assert view["fields_local"]["symptom"].startswith("[mr] ")


def test_technician_cannot_record(env):
    env.as_("tech")
    assert code(create(env)) == "not_allowed"


def test_unknown_machine(env):
    r = create(env, data={"machine_code": "XX-99"})
    assert r.status_code == 404 and code(r) == "machine_not_found"


def test_machine_code_case_insensitive(env):
    assert create(env, data={"machine_code": "hp-07"}).status_code == 202


def test_no_audio(env):
    r = create(env, files={})
    assert r.status_code == 422 and code(r) == "audio_required"


def test_wrong_file_type(env):
    r = create(env, files={"audio": ("x.pdf", b"%PDF" + b"0" * 5000, "application/pdf")})
    assert r.status_code == 415


def test_empty_audio(env):
    r = create(env, files={"audio": ("x.webm", b"tiny", "audio/webm")})
    assert r.status_code == 422 and code(r) == "audio_empty"


def test_audio_too_big(env):
    env.state["settings"] = CaptureSettings(_env_file=None, MAX_AUDIO_MB=0.01)
    r = create(env, files={"audio": ("x.webm", b"0" * 20000, "audio/webm")})
    assert r.status_code == 413


def test_user_file_name_never_used_in_path(env):
    r = create(env, files={"audio": ("../../evil.webm", AUDIO[1], "audio/webm")})
    rid = r.json()["record_id"]
    assert env.uploads[-1][1] == f"{TENANT}/{rid}.webm"


def test_text_mode_dev_only(env):
    data = {"machine_code": "HP-07", "transcript_en": "The pump was knocking, oil was low, I topped it up."}
    assert create(env, files={}, data=data).status_code == 202
    env.state["settings"] = CaptureSettings(_env_file=None, APP_ENV="production")
    r = create(env, files={}, data=data)
    assert r.status_code == 403 and code(r) == "text_mode_disabled"


# ------------------------------------------------------------------ access

def test_other_people_and_plants_get_404(env):
    rid = create(env).json()["record_id"]
    wait_ready(env, rid)
    env.as_("other_expert")
    assert env.client.get(f"/capture/records/{rid}").status_code == 404
    env.as_("other_plant_sup")
    assert env.client.get(f"/capture/records/{rid}").status_code == 404
    assert env.client.get(f"/manager/records/{rid}").status_code == 404
    env.as_("supervisor")
    assert env.client.get(f"/capture/records/{rid}").status_code == 200


def test_invalid_id(env):
    assert env.client.get("/capture/records/not-a-uuid").status_code == 422


def test_my_notes_list(env):
    rid = create(env).json()["record_id"]
    wait_ready(env, rid)
    items = env.client.get("/capture/records").json()["items"]
    assert [i["id"] for i in items] == [rid] and items[0]["audio_url"] is None
    env.as_("other_expert")
    assert env.client.get("/capture/records").json()["items"] == []


# ------------------------------------------------------------------ submit / delete

def test_submit_rules(env):
    rid = create(env).json()["record_id"]
    wait_ready(env, rid)
    env.as_("other_expert")
    assert env.client.post(f"/capture/records/{rid}/submit", json={}).status_code == 404
    env.as_("supervisor")
    assert code(env.client.post(f"/capture/records/{rid}/submit", json={})) == "not_author"
    env.as_("expert")
    bad = env.client.post(f"/capture/records/{rid}/submit", json={"edits": {"colour": "red"}})
    assert bad.status_code == 422                                  # unknown field rejected
    ok = env.client.post(f"/capture/records/{rid}/submit",
                         json={"edits": {"cause": "लॉक नट सैल"}, "edit_language": "mr-IN"})
    assert ok.status_code == 200 and ok.json()["status"] == "pending"
    assert ok.json()["fields"]["cause"] == "EN:लॉक नट सैल"
    again = env.client.post(f"/capture/records/{rid}/submit", json={})
    assert again.status_code == 409
    assert code(env.client.delete(f"/capture/records/{rid}")) == "not_deletable"


def test_discard(env):
    rid = create(env).json()["record_id"]
    wait_ready(env, rid)
    assert env.client.delete(f"/capture/records/{rid}").status_code == 204
    assert env.client.get(f"/capture/records/{rid}").status_code == 404


def test_retry_rules(env):
    env.spies["stt"].transcript = "uh"            # -> no_speech (not retryable)
    rid = create(env).json()["record_id"]
    view = wait_ready(env, rid)
    assert view["error"] == {"code": "no_speech", "retryable": False}
    assert code(env.client.post(f"/capture/records/{rid}/retry")) == "record_again"


# ------------------------------------------------------------------ supervisor review

def _pending(env):
    env.as_("expert")
    rid = create(env).json()["record_id"]
    wait_ready(env, rid)
    env.client.post(f"/capture/records/{rid}/submit", json={})
    return rid


def test_review_queue_and_approve(env):
    rid = _pending(env)
    env.as_("expert")
    assert env.client.get("/manager/review-queue").status_code == 403
    env.as_("supervisor")
    q = env.client.get("/manager/review-queue").json()
    assert q["count"] == 1 and q["items"][0]["id"] == rid and q["items"][0]["machine"]["code"] == "HP-07"
    assert env.client.get("/manager/review-queue/count").json() == {"count": 1}
    detail = env.client.get(f"/manager/records/{rid}").json()
    assert detail["can"]["review"] is True
    r = env.client.post(f"/manager/records/{rid}/approve", json={"edits": {"fix": "reset relief valve"}})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert env.spies["rebuild"].calls == [(rid,)]
    assert env.client.post(f"/manager/records/{rid}/approve", json={}).status_code == 409
    assert env.client.get("/manager/review-queue").json()["count"] == 0


def test_reject_needs_reason(env):
    rid = _pending(env)
    env.as_("supervisor")
    assert env.client.post(f"/manager/records/{rid}/reject", json={"reason": "no"}).status_code == 422
    r = env.client.post(f"/manager/records/{rid}/reject", json={"reason": "Cause not clear, please record again."})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    env.as_("expert")
    mine = env.client.get(f"/capture/records/{rid}").json()
    assert mine["reject_reason"] == "Cause not clear, please record again."


def test_cannot_approve_without_problem_and_fix(env):
    rid = _pending(env)
    env.as_("supervisor")
    r = env.client.post(f"/manager/records/{rid}/approve", json={"edits": {"fix": None}})
    assert r.status_code == 422 and code(r) == "incomplete"


def test_supervisor_cannot_review_own_record(env):
    env.as_("supervisor")
    rid = create(env).json()["record_id"]
    wait_ready(env, rid)
    env.client.post(f"/capture/records/{rid}/submit", json={})
    r = env.client.post(f"/manager/records/{rid}/approve", json={})
    assert r.status_code == 409 and code(r) == "own_record"
