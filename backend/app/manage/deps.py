"""Role checks and the dependencies tests replace (repo, auth admin)."""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from app.capture.errors import api_error

from .adapters import ManageUser, db_conn, manage_user
from .settings import get_manage_settings


def supervisor(user: ManageUser = Depends(manage_user)) -> ManageUser:
    if user.role != "supervisor":
        raise api_error(403, "forbidden_role", "Only supervisors can open this.")
    return user


def admin(user: ManageUser = Depends(supervisor)) -> ManageUser:
    if not user.is_admin:
        raise api_error(403, "admin_only", "Only plant admins can change setup.")
    return user


@lru_cache
def _repo():
    from .repo import PostgresManageRepo

    return PostgresManageRepo(db_conn)


def get_repo():
    return _repo()


@lru_cache
def _auth():
    from .auth_admin import GoTrueAdmin

    s = get_manage_settings()
    return GoTrueAdmin(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY)


def get_auth_admin():
    return _auth()


def get_rebuild():
    from .adapters import rebuild_record_chunks

    return rebuild_record_chunks
