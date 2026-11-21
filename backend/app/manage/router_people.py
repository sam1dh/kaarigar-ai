"""/admin/people — W8 People. Plant admins only.

Technicians and experts sign in with employee ID + a 6-digit PIN (Phase 0's hidden email trick).
Supervisors sign in on the web with email + password; Kaarigar gives a temporary password once.
PINs and passwords are shown once in the response and never stored or logged by Kaarigar.
People are deactivated, never deleted, so their repair records keep their author.
"""
from __future__ import annotations

import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.capture.errors import api_error
from app.capture.languages import NAMES as LANGUAGES

from .adapters import ManageUser, forget_profile
from .auth_admin import AuthAdminError, hidden_email
from .deps import admin, get_auth_admin, get_repo
from .secrets_gen import new_pin, new_temp_password
from .settings import get_manage_settings
from .views import iso, person_view

router = APIRouter(prefix="/admin/people", tags=["people"])
audit_router = APIRouter(prefix="/admin", tags=["people"])

EMPLOYEE_ID = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,19}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
AUTH_MESSAGES = {
    "login_exists": "This employee ID or email already has a login.",
    "auth_unreachable": "Couldn't reach the login service. Try again.",
    "weak_password": "The login service refused this password. Try again.",
    "login_not_found": "This person's login is missing. Ask the developer to check Supabase Auth.",
}


class NewPerson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=80)
    role: Literal["technician", "expert", "supervisor"]
    language: str = "hi-IN"
    employee_id: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=120)
    is_admin: bool = False


class PersonPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=80)
    role: Literal["technician", "expert"] | None = None
    language: str | None = None
    is_admin: bool | None = None


def _auth_error(e: AuthAdminError):
    status = 409 if e.code == "login_exists" else 502
    return api_error(status, e.code, AUTH_MESSAGES.get(e.code, "The login service returned an error."))


def _uuid(v: str) -> str:
    try:
        return str(uuid.UUID(v))
    except ValueError:
        raise api_error(422, "invalid_id", "Not a valid id.")


def _load(repo, user: ManageUser, person_id: str) -> dict:
    row = repo.get_person(user.tenant_id, _uuid(person_id))
    if not row:
        raise api_error(404, "not_found", "Person not found.")
    return row


def _check_language(code: str) -> str:
    if code not in LANGUAGES:
        raise api_error(422, "unsupported_language", "Pick one of the app's languages.")
    return code


@router.get("")
def list_people(user: ManageUser = Depends(admin), repo=Depends(get_repo)):
    items = [person_view(r, viewer_id=user.id) for r in repo.list_people(user.tenant_id)]
    counts = {s: sum(1 for i in items if i["status"] == s) for s in ("active", "new", "deactivated")}
    return {"items": items, "counts": counts}


@router.post("", status_code=201)
def add_person(body: NewPerson, user: ManageUser = Depends(admin), repo=Depends(get_repo),
               auth=Depends(get_auth_admin)):
    s = get_manage_settings()
    name = " ".join(body.name.split())
    language = _check_language(body.language)
    employee_id = body.employee_id.strip().upper() if body.employee_id and body.employee_id.strip() else None
    if employee_id and not EMPLOYEE_ID.match(employee_id):
        raise api_error(422, "bad_employee_id", "Employee ID: 2–20 letters, digits or dashes, like SH-0521.")
    if employee_id and repo.employee_id_taken(user.tenant_id, employee_id):
        raise api_error(409, "employee_id_taken", f"{employee_id} is already used in this plant.")
    if body.is_admin and body.role != "supervisor":
        raise api_error(422, "admin_needs_supervisor", "Only supervisors can be plant admins.")

    tenant = repo.tenant(user.tenant_id)
    if body.role in ("technician", "expert"):
        if not employee_id:
            raise api_error(422, "employee_id_required", "Technicians and experts sign in with an employee ID.")
        email = hidden_email(employee_id, tenant["slug"], s.EMPLOYEE_EMAIL_DOMAIN)
        secret = new_pin()
    else:
        email = (body.email or "").strip().lower()
        if not EMAIL.match(email):
            raise api_error(422, "email_required", "Supervisors sign in on the web with their work email.")
        secret = new_temp_password()

    try:
        new_id = auth.create_user(email, secret, name=name)
    except AuthAdminError as e:
        raise _auth_error(e)
    try:
        repo.insert_person(user_id=new_id, tenant_id=user.tenant_id, name=name, employee_id=employee_id,
                           role=body.role, is_admin=body.is_admin, language=language, created_by=user.id)
    except Exception:
        try:                      # don't leave a login with no person behind it
            auth.delete_user(new_id)
        except AuthAdminError:
            pass
        raise api_error(500, "save_failed", "Couldn't save this person. Nothing was created; try again.")
    repo.audit(user.tenant_id, user.id, "person_added", "user", new_id,
               {"role": body.role, "employee_id": employee_id, "is_admin": body.is_admin})
    person = person_view(repo.get_person(user.tenant_id, new_id), viewer_id=user.id)
    login = ({"method": "pin", "plant_code": tenant["slug"], "employee_id": employee_id, "pin": secret}
             if body.role != "supervisor" else {"method": "email", "email": email, "temp_password": secret})
    return {"person": person, "login": login, "shown_once": True}


@router.patch("/{person_id}")
def update_person(person_id: str, body: PersonPatch, user: ManageUser = Depends(admin), repo=Depends(get_repo)):
    row = _load(repo, user, person_id)
    changes: dict = {}
    if body.name is not None:
        changes["name"] = " ".join(body.name.split())
    if body.language is not None:
        changes["language"] = _check_language(body.language)
    if body.role is not None and body.role != row["role"]:
        if row["role"] == "supervisor":
            raise api_error(409, "role_change_needs_new_login",
                            "Supervisors sign in with email. Add this person again with an employee ID instead.")
        if str(row["id"]) == user.id:
            raise api_error(409, "own_role", "You can't change your own role.")
        changes["role"] = body.role
    if body.is_admin is not None and body.is_admin != bool(row["is_admin"]):
        if row["role"] != "supervisor":
            raise api_error(422, "admin_needs_supervisor", "Only supervisors can be plant admins.")
        if not body.is_admin and str(row["id"]) == user.id:
            raise api_error(409, "own_admin", "You can't remove your own admin access.")
        if not body.is_admin and repo.active_admin_count(user.tenant_id) <= 1:
            raise api_error(409, "last_admin", "The plant needs at least one admin.")
        changes["is_admin"] = body.is_admin
    if changes:
        repo.update_person(user.tenant_id, str(row["id"]), **changes)
        forget_profile(str(row["id"]))          # role/admin/language change applies next request
        repo.audit(user.tenant_id, user.id, "person_updated", "user", str(row["id"]),
                   {k: v for k, v in changes.items()})
    return person_view(repo.get_person(user.tenant_id, str(row["id"])), viewer_id=user.id)


@router.post("/{person_id}/reset-login")
def reset_login(person_id: str, user: ManageUser = Depends(admin), repo=Depends(get_repo), auth=Depends(get_auth_admin)):
    row = _load(repo, user, person_id)
    if row.get("deactivated_at"):
        raise api_error(409, "deactivated", "Reactivate this person first.")
    if str(row["id"]) == user.id:
        raise api_error(409, "own_login", "Change your own password from the login page.")
    pin_login = row["role"] in ("technician", "expert")
    secret = new_pin() if pin_login else new_temp_password()
    try:
        auth.set_password(str(row["id"]), secret)
    except AuthAdminError as e:
        raise _auth_error(e)
    repo.audit(user.tenant_id, user.id, "pin_reset" if pin_login else "password_reset", "user", str(row["id"]), {})
    login = ({"method": "pin", "employee_id": row.get("employee_id"), "pin": secret} if pin_login
             else {"method": "email", "email": row.get("email"), "temp_password": secret})
    return {"login": login, "shown_once": True}


@router.post("/{person_id}/deactivate")
def deactivate(person_id: str, user: ManageUser = Depends(admin), repo=Depends(get_repo), auth=Depends(get_auth_admin)):
    row = _load(repo, user, person_id)
    if str(row["id"]) == user.id:
        raise api_error(409, "own_account", "You can't deactivate yourself.")
    if row.get("deactivated_at"):
        raise api_error(409, "already_deactivated", "Already deactivated.")
    if row["is_admin"] and repo.active_admin_count(user.tenant_id) <= 1:
        raise api_error(409, "last_admin", "The plant needs at least one admin.")
    try:
        auth.set_blocked(str(row["id"]), True)      # blocks sign-in first; nothing changes if this fails
    except AuthAdminError as e:
        raise _auth_error(e)
    repo.set_deactivated(user.tenant_id, str(row["id"]), True)
    forget_profile(str(row["id"]))              # cached token stops working on its next request
    repo.audit(user.tenant_id, user.id, "person_deactivated", "user", str(row["id"]), {})
    return person_view(repo.get_person(user.tenant_id, str(row["id"])), viewer_id=user.id)


@router.post("/{person_id}/reactivate")
def reactivate(person_id: str, user: ManageUser = Depends(admin), repo=Depends(get_repo), auth=Depends(get_auth_admin)):
    row = _load(repo, user, person_id)
    if not row.get("deactivated_at"):
        raise api_error(409, "not_deactivated", "This person is active.")
    try:
        auth.set_blocked(str(row["id"]), False)
    except AuthAdminError as e:
        raise _auth_error(e)
    repo.set_deactivated(user.tenant_id, str(row["id"]), False)
    forget_profile(str(row["id"]))
    repo.audit(user.tenant_id, user.id, "person_reactivated", "user", str(row["id"]), {})
    return person_view(repo.get_person(user.tenant_id, str(row["id"])), viewer_id=user.id)


@audit_router.get("/audit")
def audit_log(limit: int = Query(50, ge=1, le=200), user: ManageUser = Depends(admin), repo=Depends(get_repo)):
    return {"items": [{"id": str(r["id"]), "action": r["action"], "target_type": r["target_type"],
                       "target_id": str(r["target_id"]) if r.get("target_id") else None, "detail": r.get("detail"),
                       "actor": r.get("actor_name"), "created_at": iso(r["created_at"])}
                      for r in repo.audit_list(user.tenant_id, limit)]}
