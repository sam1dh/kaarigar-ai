"""Phase 4 API tests with in-memory fakes (no Supabase, no network)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.capture import adapters as capture_adapters
from app.manage import deps
from app.manage.adapters import ManageUser
from app.manage.router_analytics import router as analytics_router
from app.manage.router_knowledge import router as knowledge_router
from app.manage.router_logs import router as logs_router
from app.manage.router_machines import code_key, normalize_code, router as machines_router
from app.manage.router_people import audit_router, router as people_router

from .fakes import (AMIT, CNC03, HP07, MODEL_HPX, OTHER, OTHER_ADMIN, RAMESH, REC1, REC_PENDING, SUPER, SUPER2,
                    TENANT, FakeAuth, FakeRepo)


def as_user(uid: str, repo: FakeRepo) -> ManageUser:
    u = repo.users[uid]
    return ManageUser(id=uid, tenant_id=u["tenant_id"], role=u["role"], is_admin=u["is_admin"],
                      language=u["language"], name=u["name"])


@pytest.fixture
def env():
    repo, auth, rebuilt = FakeRepo(), FakeAuth(), []
    state = {"uid": SUPER, "rebuild_fail": False}
    app = FastAPI()
    for r in (people_router, audit_router, machines_router, knowledge_router, analytics_router, logs_router):
        app.include_router(r)

    def rebuild(rid):
        if state["rebuild_fail"]:
            raise RuntimeError("embed down")
        rebuilt.append(rid)

    app.dependency_overrides[capture_adapters.capture_user] = lambda: as_user(state["uid"], repo)
    app.dependency_overrides[deps.get_repo] = lambda: repo
    app.dependency_overrides[deps.get_auth_admin] = lambda: auth
    app.dependency_overrides[deps.get_rebuild] = lambda: rebuild
    c = TestClient(app)
    c.repo, c.fauth, c.state, c.rebuilt = repo, auth, state, rebuilt
    return c


def err(r):
    return r.json()["detail"]["error"]["code"]


# ---------------------------------------------------------------- roles

@pytest.mark.parametrize("path", ["/admin/people", "/admin/machines", "/admin/log-imports", "/admin/audit",
                                  "/admin/maintenance-logs"])
def test_admin_screens_need_admin(env, path):
    env.state["uid"] = SUPER2
    r = env.get(path)
    assert r.status_code == 403 and err(r) == "admin_only"
    env.state["uid"] = AMIT
    assert err(env.get(path)) == "forbidden_role"


@pytest.mark.parametrize("path", ["/manager/knowledge/stats", "/manager/knowledge/items", "/manager/analytics"])
def test_manager_screens_any_supervisor(env, path):
    env.state["uid"] = SUPER2
    assert env.get(path).status_code == 200
    env.state["uid"] = RAMESH
    r = env.get(path)
    assert r.status_code == 403 and err(r) == "forbidden_role"


# ---------------------------------------------------------------- people

def test_list_people_counts_and_scope(env):
    r = env.get("/admin/people").json()
    ids = {p["id"] for p in r["items"]}
    assert OTHER_ADMIN not in ids and AMIT in ids
    me = next(p for p in r["items"] if p["id"] == SUPER)
    assert me["is_you"] is True
    assert sum(r["counts"].values()) == len(r["items"])


def test_add_technician_returns_pin_once_and_audits_without_pin(env):
    r = env.post("/admin/people", json={"name": "  Vijay   More ", "role": "technician", "employee_id": "sh-0521",
                                        "language": "mr-IN"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["shown_once"] is True
    login = body["login"]
    assert login["method"] == "pin" and login["employee_id"] == "SH-0521" and login["plant_code"] == "shree"
    assert len(login["pin"]) == 6 and login["pin"].isdigit()
    assert body["person"]["name"] == "Vijay More" and body["person"]["employee_id"] == "SH-0521"
    created = [c for c in env.fauth.calls if c[0] == "create"][0]
    assert created[1] == "sh-0521@shree.employees.kaarigar.app"
    audit = env.repo.audits[-1]
    assert audit["action"] == "person_added"
    assert login["pin"] not in str(audit)          # never stored


def test_add_supervisor_gets_temp_password(env):
    r = env.post("/admin/people", json={"name": "Neha Rao", "role": "supervisor", "email": "Neha@Shree.in",
                                        "is_admin": True, "language": "en-IN"})
    assert r.status_code == 201, r.text
    login = r.json()["login"]
    assert login["method"] == "email" and login["email"] == "neha@shree.in"
    assert len(login["temp_password"]) == 12
    assert r.json()["person"]["is_admin"] is True


@pytest.mark.parametrize("body,code", [
    ({"name": "X Y", "role": "technician"}, "employee_id_required"),
    ({"name": "X Y", "role": "technician", "employee_id": "SH 05"}, "bad_employee_id"),
    ({"name": "X Y", "role": "technician", "employee_id": "sh-0412"}, "employee_id_taken"),
    ({"name": "X Y", "role": "expert", "employee_id": "SH-9", "is_admin": True}, "admin_needs_supervisor"),
    ({"name": "X Y", "role": "supervisor"}, "email_required"),
    ({"name": "X Y", "role": "supervisor", "email": "not-an-email"}, "email_required"),
    ({"name": "X Y", "role": "technician", "employee_id": "SH-9", "language": "fr-FR"}, "unsupported_language"),
])
def test_add_person_validation(env, body, code):
    r = env.post("/admin/people", json=body)
    assert r.status_code in (409, 422) and err(r) == code
    assert not [c for c in env.fauth.calls if c[0] == "create"]


def test_add_person_rejects_unknown_fields(env):
    r = env.post("/admin/people", json={"name": "X Y", "role": "technician", "employee_id": "SH-9", "pin": "123456"})
    assert r.status_code == 422


def test_add_person_login_exists_and_auth_down(env):
    env.post("/admin/people", json={"name": "A B", "role": "technician", "employee_id": "SH-0900"})
    env.repo.users = {k: v for k, v in env.repo.users.items() if v.get("employee_id") != "SH-0900"}
    r = env.post("/admin/people", json={"name": "A B", "role": "technician", "employee_id": "SH-0900"})
    assert r.status_code == 409 and err(r) == "login_exists"
    env.fauth.fail = "auth_unreachable"
    r = env.post("/admin/people", json={"name": "C D", "role": "technician", "employee_id": "SH-0901"})
    assert r.status_code == 502 and err(r) == "auth_unreachable"


def test_add_person_rolls_back_login_when_db_fails(env):
    env.repo.fail_insert_person = True
    r = env.post("/admin/people", json={"name": "A B", "role": "technician", "employee_id": "SH-0950"})
    assert r.status_code == 500 and err(r) == "save_failed"
    assert any(c[0] == "delete" for c in env.fauth.calls)
    assert env.fauth.users == {}


def test_update_person_rules(env):
    r = env.patch(f"/admin/people/{AMIT}", json={"role": "expert", "language": "hi-IN", "name": "Amit  Kale"})
    assert r.status_code == 200 and r.json()["role"] == "expert"
    assert err(env.patch(f"/admin/people/{SUPER2}", json={"role": "expert"})) == "role_change_needs_new_login"
    assert err(env.patch(f"/admin/people/{AMIT}", json={"is_admin": True})) == "admin_needs_supervisor"
    assert err(env.patch(f"/admin/people/{SUPER}", json={"is_admin": False})) == "own_admin"
    assert err(env.patch(f"/admin/people/{AMIT}", json={"language": "xx"})) == "unsupported_language"
    assert env.patch(f"/admin/people/{AMIT}", json={"role": "supervisor"}).status_code == 422


def test_promote_and_last_admin(env):
    assert env.patch(f"/admin/people/{SUPER2}", json={"is_admin": True}).json()["is_admin"] is True
    env.state["uid"] = SUPER2
    assert env.patch(f"/admin/people/{SUPER}", json={"is_admin": False}).json()["is_admin"] is False
    # now SUPER2 is the only admin
    env.repo.users[SUPER]["is_admin"] = False
    r = env.post(f"/admin/people/{SUPER2}/deactivate")
    assert err(r) == "own_account"


def test_last_admin_cannot_be_removed_by_another_admin(env):
    env.repo.users[SUPER2]["is_admin"] = True
    env.repo.users[SUPER2]["deactivated_at"] = None
    env.repo.users[SUPER]["deactivated_at"] = None
    # deactivate SUPER2 (allowed: SUPER remains)
    assert env.post(f"/admin/people/{SUPER2}/deactivate").status_code == 200
    # SUPER is now the only active admin; nobody else can remove them, and they can't remove themselves
    assert err(env.patch(f"/admin/people/{SUPER}", json={"is_admin": False})) == "own_admin"


def test_patch_last_admin_guard(env):
    env.repo.users[SUPER2]["is_admin"] = True
    env.repo.users[SUPER]["deactivated_at"] = env.repo.users[SUPER]["created_at"]   # SUPER gone
    env.state["uid"] = SUPER2
    env.repo.users[SUPER]["is_admin"] = True  # counted? no: deactivated
    assert env.repo.active_admin_count(TENANT) == 1


def test_reset_login(env):
    r = env.post(f"/admin/people/{AMIT}/reset-login")
    assert r.status_code == 200
    pin = r.json()["login"]["pin"]
    assert len(pin) == 6 and env.fauth.users[AMIT]["password"] == pin
    assert env.repo.audits[-1]["action"] == "pin_reset" and pin not in str(env.repo.audits[-1])
    r = env.post(f"/admin/people/{SUPER2}/reset-login").json()
    assert r["login"]["method"] == "email" and len(r["login"]["temp_password"]) == 12
    assert err(env.post(f"/admin/people/{SUPER}/reset-login")) == "own_login"


def test_deactivate_and_reactivate(env):
    r = env.post(f"/admin/people/{AMIT}/deactivate")
    assert r.status_code == 200 and r.json()["status"] == "deactivated"
    assert env.fauth.users[AMIT]["blocked"] is True
    assert err(env.post(f"/admin/people/{AMIT}/deactivate")) == "already_deactivated"
    assert err(env.post(f"/admin/people/{AMIT}/reset-login")) == "deactivated"
    r = env.post(f"/admin/people/{AMIT}/reactivate")
    assert r.json()["status"] != "deactivated" and env.fauth.users[AMIT]["blocked"] is False
    assert err(env.post(f"/admin/people/{AMIT}/reactivate")) == "not_deactivated"


def test_deactivate_keeps_person_if_auth_fails(env):
    env.fauth.fail = "auth_unreachable"
    r = env.post(f"/admin/people/{AMIT}/deactivate")
    assert r.status_code == 502
    assert env.repo.users[AMIT]["deactivated_at"] is None


def test_people_other_plant_and_bad_ids(env):
    assert env.patch(f"/admin/people/{OTHER_ADMIN}", json={"name": "Hack Er"}).status_code == 404
    assert env.post(f"/admin/people/{OTHER_ADMIN}/deactivate").status_code == 404
    assert err(env.post("/admin/people/not-a-uuid/deactivate")) == "invalid_id"


def test_audit_list(env):
    env.post(f"/admin/people/{AMIT}/deactivate")
    items = env.get("/admin/audit").json()["items"]
    assert items[0]["action"] == "person_deactivated" and items[0]["actor"] == "Suresh Kulkarni"


# ---------------------------------------------------------------- machines

@pytest.mark.parametrize("raw,norm,key", [
    ("hp 07", "HP-07", "HP7"), ("HP-7", "HP-7", "HP7"), ("cnc-003", "CNC-003", "CNC3"), ("Ac01", "AC01", "AC1"),
    ("hp-12b", "HP-12B", "HP12B"),
])
def test_code_rules(raw, norm, key):
    assert normalize_code(raw) == norm and code_key(norm) == key


def test_list_machines(env):
    r = env.get("/admin/machines").json()
    hp = next(i for i in r["items"] if i["code"] == "HP-07")
    assert hp["qr_url"] == "https://app.kaarigar-ai.online/m/" + "a" * 24
    assert r["counts"] == {"active": 2, "archived": 0, "stickers_missing": 1}


def test_add_machine_with_new_model(env):
    r = env.post("/admin/machines", json={"code": "ac 01", "name": "Air compressor", "line": " Utility ",
                                          "new_model": {"model": "AirPro 7", "type": "compressor"}})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["code"] == "AC-01" and m["line"] == "Utility" and m["model"]["model"] == "AirPro 7"
    assert m["sticker_printed_at"] is None
    # same model name again reuses it
    r2 = env.post("/admin/machines", json={"code": "AC-02", "new_model": {"model": "airpro 7"}}).json()
    assert r2["model"]["id"] == m["model"]["id"]


@pytest.mark.parametrize("code,err_code", [("HP 7", "code_taken"), ("hp-007", "code_taken"), ("07", "bad_code"),
                                           ("PRESS-A", "bad_code")])
def test_add_machine_code_checks(env, code, err_code):
    r = env.post("/admin/machines", json={"code": code})
    assert err(r) == err_code


def test_add_machine_model_checks(env):
    assert err(env.post("/admin/machines", json={"code": "HP-08", "model_id": MODEL_HPX,
                                                 "new_model": {"model": "Z"}})) == "one_model"
    assert err(env.post("/admin/machines", json={"code": "HP-08",
                                                 "model_id": "99999999-0000-0000-0000-000000000000"})) == "model_not_found"
    env.repo.models["99999999-0000-0000-0000-000000000001"] = {"id": "99999999-0000-0000-0000-000000000001",
                                                               "tenant_id": OTHER, "model": "Theirs"}
    assert err(env.post("/admin/machines", json={"code": "HP-08",
                                                 "model_id": "99999999-0000-0000-0000-000000000001"})) == "model_not_found"


def test_update_machine(env):
    r = env.patch(f"/admin/machines/{CNC03}", json={"code": "cnc 3", "line": None, "model_id": MODEL_HPX})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["code"] == "CNC-3" and m["line"] is None and m["model"]["model"] == "HPX-200"
    assert err(env.patch(f"/admin/machines/{CNC03}", json={"code": "HP-7"})) == "code_taken"
    # renaming to its own code (different spelling) is fine
    assert env.patch(f"/admin/machines/{HP07}", json={"code": "HP-007"}).status_code == 200


def test_archive_restore_new_qr(env):
    r = env.post(f"/admin/machines/{HP07}/archive").json()
    assert r["archived"] is True
    assert err(env.post(f"/admin/machines/{HP07}/archive")) == "already_archived"
    assert env.get("/admin/machines").json()["counts"]["active"] == 1
    assert len(env.get("/admin/machines?include_archived=true").json()["items"]) == 2
    assert env.post(f"/admin/machines/{HP07}/restore").json()["archived"] is False
    assert err(env.post(f"/admin/machines/{HP07}/restore")) == "not_archived"
    old = env.repo.machines[HP07]["qr_token"]
    r = env.post(f"/admin/machines/{HP07}/new-qr").json()
    assert old not in r["qr_url"] and r["sticker_printed_at"] is None
    assert env.repo.audits[-1]["action"] == "qr_renewed"


def test_stickers(env):
    r = env.post("/admin/machines/stickers", json={"machine_ids": [HP07, CNC03, HP07]})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["code"] for i in items] == ["CNC-03", "HP-07"]
    assert items[0]["svg"].startswith("<svg") and "viewBox" in items[0]["svg"] and "QR code for CNC-03" in items[0]["svg"]
    assert items[1]["url"].endswith("/m/" + "a" * 24)
    r = env.post("/admin/machines/stickers/printed", json={"machine_ids": [CNC03]})
    assert r.json() == {"marked": 1}
    assert env.get("/admin/machines").json()["counts"]["stickers_missing"] == 0


def test_stickers_limits(env):
    assert env.post("/admin/machines/stickers", json={"machine_ids": []}).status_code == 422
    ids = [f"dddddddd-0000-0000-0000-{i:012d}" for i in range(61)]
    assert err(env.post("/admin/machines/stickers", json={"machine_ids": ids})) == "too_many"
    assert err(env.post("/admin/machines/stickers",
                        json={"machine_ids": ["dddddddd-0000-0000-0000-000000000999"]})) == "not_found"


def test_add_model(env):
    r = env.post("/admin/machine-models", json={"model": "CNC-L5", "oem": "Ace"})
    assert r.status_code == 201 and r.json()["model"] == "CNC-L5"
    assert err(env.post("/admin/machine-models", json={"model": "hpx-200"})) == "model_exists"


def test_machines_other_plant(env):
    env.repo.machines["dddddddd-0000-0000-0000-000000000099"] = dict(
        id="dddddddd-0000-0000-0000-000000000099", tenant_id=OTHER, code="X-1", name=None, line=None, model_id=None,
        qr_token="c" * 24, created_at=None, archived_at=None, sticker_printed_at=None)
    assert env.post("/admin/machines/dddddddd-0000-0000-0000-000000000099/archive").status_code == 404
    assert err(env.post("/admin/machines/stickers",
                        json={"machine_ids": ["dddddddd-0000-0000-0000-000000000099"]})) == "not_found"
    assert "HP-07" in {m["code"] for m in env.get("/admin/machines").json()["items"]}
    # other plant's code doesn't block ours
    assert env.post("/admin/machines", json={"code": "X-1"}).status_code == 201


# ---------------------------------------------------------------- knowledge

def test_knowledge_stats(env):
    s = env.get("/manager/knowledge/stats").json()
    assert s["answered_rate_30d"] == 0.8


def test_knowledge_items_mixed_and_filters(env):
    items = env.get("/manager/knowledge/items").json()["items"]
    assert {i["kind"] for i in items} == {"E", "M", "H"}
    rec = next(i for i in items if i["kind"] == "E")
    assert rec["title"] == "pressure not building → reset relief valve" and rec["used"] == 5
    assert [i["kind"] for i in env.get("/manager/knowledge/items?kind=M").json()["items"]] == ["M"]
    used = env.get("/manager/knowledge/items?sort=used").json()["items"]
    assert [i["used"] for i in used] == sorted([i["used"] for i in used], reverse=True)
    q = env.get("/manager/knowledge/items?q=relief").json()["items"]
    assert [i["kind"] for i in q] == ["E"]
    assert env.get("/manager/knowledge/items?kind=X").status_code == 422


def test_archive_and_restore_record(env):
    r = env.post(f"/manager/knowledge/records/{REC1}/archive")
    assert r.json()["status"] == "archived" and REC1 not in env.repo.chunks
    assert env.get("/manager/knowledge/items?kind=E").json()["items"] == []
    assert len(env.get("/manager/knowledge/items?archived=true").json()["items"]) == 1
    assert err(env.post(f"/manager/knowledge/records/{REC1}/archive")) == "already_archived"
    r = env.post(f"/manager/knowledge/records/{REC1}/restore")
    assert r.json() == {"id": REC1, "status": "ready"} and env.rebuilt == [REC1]
    assert err(env.post(f"/manager/knowledge/records/{REC1}/restore")) == "not_archived"


def test_restore_warns_when_search_rebuild_fails(env):
    env.post(f"/manager/knowledge/records/{REC1}/archive")
    env.state["rebuild_fail"] = True
    r = env.post(f"/manager/knowledge/records/{REC1}/restore").json()
    assert r["warning"] == "search_not_updated" and env.repo.records[REC1]["archived_at"] is None


def test_archive_needs_approved(env):
    assert err(env.post(f"/manager/knowledge/records/{REC_PENDING}/archive")) == "not_approved"
    assert env.post("/manager/knowledge/records/eeeeeeee-0000-0000-0000-000000000999/archive").status_code == 404
    assert err(env.post("/manager/knowledge/records/zzz/archive")) == "invalid_id"


def test_non_admin_supervisor_can_archive(env):
    env.state["uid"] = SUPER2
    assert env.post(f"/manager/knowledge/records/{REC1}/archive").status_code == 200


# ---------------------------------------------------------------- analytics + logs

def test_analytics(env):
    r = env.get("/manager/analytics?days=7")
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["days"] == 7 and len(a["per_day"]) == 7
    assert a["questions"]["answered_rate"] == 0.8 and a["questions"]["first_word_ms"] == 1840
    assert a["escalations"]["minutes_to_answer"] == 42 and a["notes"]["hours_to_review"] == 5.2
    assert a["team"][0]["name"] == "Ramesh Patil"
    assert env.get("/manager/analytics?days=14").status_code == 422


def test_logs(env):
    imports = env.get("/admin/log-imports").json()["items"]
    assert imports[0]["rows_ok"] == 56 and imports[0]["created_by"] == "Suresh Kulkarni"
    logs = env.get("/admin/maintenance-logs?machine=HP-07").json()["items"]
    assert logs[0]["date"].startswith("2025-10-03") and logs[0]["machine"] == "HP-07"


def test_all_routes_registered_without_clashes():
    from app.manage.routers import manage_routers

    app = FastAPI()
    for r in manage_routers:
        app.include_router(r)
    # read from OpenAPI: works on every FastAPI version (newer ones wrap included routers)
    routes = [(m.upper(), path) for path, ops in app.openapi()["paths"].items() for m in ops]
    assert len(routes) == len(set(routes)) == 23
    assert ("POST", "/admin/people") in routes and ("GET", "/manager/analytics") in routes
    assert ("POST", "/admin/machines/stickers") in routes and ("GET", "/admin/audit") in routes
    # Phase 1 owns these; Phase 4 must not redefine them
    for phase1 in [("GET", "/admin/machine-models"), ("POST", "/admin/log-imports"), ("GET", "/admin/documents"),
                   ("GET", "/admin/log-imports/{import_id}"), ("GET", "/admin/jobs/{job_id}")]:
        assert phase1 not in routes
