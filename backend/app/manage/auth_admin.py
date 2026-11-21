"""Supabase Auth admin API (GoTrue) over plain HTTP with the service-role key.

Plain REST keeps us independent of the supabase-py version:
  POST   {SUPABASE_URL}/auth/v1/admin/users            create a login (email_confirm: true)
  PUT    {SUPABASE_URL}/auth/v1/admin/users/{id}       change password / ban_duration
  DELETE {SUPABASE_URL}/auth/v1/admin/users/{id}       undo a create when our own insert fails
Technicians and experts log in with PIN = password on a hidden email (Phase 0):
  "<employee_id lower>@<plant slug>.<EMPLOYEE_EMAIL_DOMAIN>"
Never logs passwords, PINs or keys.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("kaarigar.manage.auth_admin")

BAN_FOREVER = "876000h"     # ~100 years: GoTrue's way to block sign-in


class AuthAdminError(Exception):
    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


def hidden_email(employee_id: str, plant_slug: str, domain: str) -> str:
    return f"{employee_id.strip().lower()}@{plant_slug.strip().lower()}.{domain.strip().lower()}"


class GoTrueAdmin:
    def __init__(self, supabase_url: str, service_key: str, *, http: httpx.Client | None = None, timeout: float = 15.0):
        if not supabase_url or not service_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        self._http = http or httpx.Client(
            base_url=supabase_url.rstrip("/") + "/auth/v1",
            timeout=timeout,
            headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
        )

    def _check(self, r: httpx.Response, action: str) -> dict:
        if r.status_code in (200, 201):
            return r.json() if r.content else {}
        body = {}
        try:
            body = r.json()
        except ValueError:
            pass
        msg = str(body.get("msg") or body.get("message") or body.get("error_description") or body.get("error") or "")
        code = str(body.get("error_code") or body.get("code") or "")
        log.warning("auth admin %s failed status=%s code=%s", action, r.status_code, code)
        if r.status_code == 422 and ("already" in msg.lower() or code in ("email_exists", "user_already_exists")):
            raise AuthAdminError("login_exists", r.status_code)
        if r.status_code == 422 and ("password" in msg.lower() or code == "weak_password"):
            raise AuthAdminError("weak_password", r.status_code)
        if r.status_code == 404:
            raise AuthAdminError("login_not_found", r.status_code)
        raise AuthAdminError("auth_failed", r.status_code)

    def create_user(self, email: str, password: str, *, name: str | None = None) -> str:
        try:
            r = self._http.post("/admin/users", json={
                "email": email, "password": password, "email_confirm": True,
                "user_metadata": {"name": name} if name else {},
            })
        except httpx.HTTPError as e:
            raise AuthAdminError("auth_unreachable") from e
        data = self._check(r, "create")
        uid = data.get("id") or (data.get("user") or {}).get("id")
        if not uid:
            raise AuthAdminError("auth_failed")
        return str(uid)

    def set_password(self, user_id: str, password: str) -> None:
        try:
            r = self._http.put(f"/admin/users/{user_id}", json={"password": password})
        except httpx.HTTPError as e:
            raise AuthAdminError("auth_unreachable") from e
        self._check(r, "set_password")

    def set_blocked(self, user_id: str, blocked: bool) -> None:
        try:
            r = self._http.put(f"/admin/users/{user_id}", json={"ban_duration": BAN_FOREVER if blocked else "none"})
        except httpx.HTTPError as e:
            raise AuthAdminError("auth_unreachable") from e
        self._check(r, "set_blocked")

    def delete_user(self, user_id: str) -> None:
        try:
            r = self._http.delete(f"/admin/users/{user_id}")
        except httpx.HTTPError as e:
            raise AuthAdminError("auth_unreachable") from e
        if r.status_code not in (200, 204, 404):
            self._check(r, "delete")
