"""GoTrueAdmin against a mocked HTTP transport (no real Supabase)."""
import json

import httpx
import pytest

from app.manage.auth_admin import BAN_FOREVER, AuthAdminError, GoTrueAdmin


def client(handler):
    seen = []

    def wrap(req: httpx.Request):
        seen.append(req)
        return handler(req)

    http = httpx.Client(base_url="https://x.supabase.co/auth/v1", transport=httpx.MockTransport(wrap),
                        headers={"apikey": "k", "Authorization": "Bearer k"})
    return GoTrueAdmin("https://x.supabase.co", "k", http=http), seen


def test_create_user_sends_confirmed_email():
    g, seen = client(lambda r: httpx.Response(200, json={"id": "u-1"}))
    assert g.create_user("a@b.in", "284719", name="Amit") == "u-1"
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/auth/v1/admin/users" and body["email_confirm"] is True
    assert body["user_metadata"] == {"name": "Amit"} and seen[0].headers["apikey"] == "k"


@pytest.mark.parametrize("status,body,code", [
    (422, {"msg": "A user with this email address has already been registered"}, "login_exists"),
    (422, {"error_code": "email_exists"}, "login_exists"),
    (422, {"error_code": "weak_password", "msg": "Password should be"}, "weak_password"),
    (404, {"msg": "User not found"}, "login_not_found"),
    (500, {}, "auth_failed"),
    (401, {"msg": "Invalid API key"}, "auth_failed"),
])
def test_errors_map_to_codes(status, body, code):
    g, _ = client(lambda r: httpx.Response(status, json=body))
    with pytest.raises(AuthAdminError) as e:
        g.create_user("a@b.in", "x")
    assert e.value.code == code


def test_unreachable():
    def boom(r):
        raise httpx.ConnectError("down")
    g, _ = client(boom)
    with pytest.raises(AuthAdminError) as e:
        g.set_password("u-1", "284719")
    assert e.value.code == "auth_unreachable"


def test_block_unblock_and_delete():
    g, seen = client(lambda r: httpx.Response(404 if r.method == "DELETE" else 200, json={}))
    g.set_blocked("u-1", True)
    g.set_blocked("u-1", False)
    g.delete_user("u-1")                       # 404 is fine (already gone)
    assert json.loads(seen[0].content) == {"ban_duration": BAN_FOREVER}
    assert json.loads(seen[1].content) == {"ban_duration": "none"}
    assert seen[0].method == "PUT" and seen[0].url.path == "/auth/v1/admin/users/u-1"


def test_needs_config():
    with pytest.raises(RuntimeError):
        GoTrueAdmin("", "")


def test_never_logs_secrets(caplog):
    g, _ = client(lambda r: httpx.Response(500, json={"msg": "boom"}))
    with pytest.raises(AuthAdminError):
        g.create_user("a@b.in", "SuperSecret9X")
    assert "SuperSecret9X" not in caplog.text
