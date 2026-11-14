"""Supabase JWT verification and role dependencies."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt
from fastapi import Depends, Request

from app.core.errors import ApiError
from app.core.supabase import admin_client

logger = logging.getLogger("kaarigar.auth")

_CACHE_TTL = 300  # seconds


@dataclass
class CurrentUser:
    id: str
    tenant_id: str
    name: str
    employee_id: str | None
    role: str
    is_admin: bool
    language: str


# ---- JWKS (cached for _CACHE_TTL) ----
_jwk_client: jwt.PyJWKClient | None = None


def _get_jwk_client(jwks_url: str) -> jwt.PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        # PyJWKClient caches keys internally (cache_keys=True) and refreshes after `lifespan`.
        _jwk_client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=_CACHE_TTL)
    return _jwk_client


def _verify_token(token: str, settings) -> dict:
    """Verify a Supabase access token; return its claims."""
    if settings.supabase_jwt_secret:
        # Legacy HS256 secret.
        try:
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                options={"verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise ApiError(401, "invalid_token", "Session expired. Please sign in again.") from exc

    jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    try:
        jwk_client = _get_jwk_client(jwks_url)
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            options={"verify_aud": False},
        )
        return claims
    except jwt.PyJWTError as exc:
        # JWKS fetch/network problems surface as PyJWKClientError (a PyJWKError subclass).
        raise ApiError(401, "invalid_token", "Session expired. Please sign in again.") from exc


def load_profile(user_id: str) -> CurrentUser:
    """Load the users row for an auth user (service-role client, bypasses RLS)."""
    row = (
        admin_client()
        .table("users")
        .select("id, tenant_id, name, employee_id, role, is_admin, language")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    data = row.data or []
    if not data:
        raise ApiError(403, "profile_missing", "No user profile for this account.")
    d = data[0]
    return CurrentUser(
        id=str(d["id"]),
        tenant_id=str(d["tenant_id"]),
        name=d["name"],
        employee_id=d.get("employee_id"),
        role=d["role"],
        is_admin=bool(d["is_admin"]),
        language=d["language"],
    )


def load_profile_with_tenant(user_id: str) -> tuple[CurrentUser, dict]:
    """Profile + tenant in a single REST call (PostgREST embeds tenants via the FK)."""
    row = (
        admin_client()
        .table("users")
        .select(
            "id, tenant_id, name, employee_id, role, is_admin, language, tenant:tenants(id, name, slug)"
        )
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    data = row.data or []
    if not data:
        raise ApiError(403, "profile_missing", "No user profile for this account.")
    d = data[0]
    tenant_raw = d.get("tenant") or {}
    if not tenant_raw:
        raise ApiError(403, "profile_missing", "No plant found for this account.")
    user = CurrentUser(
        id=str(d["id"]),
        tenant_id=str(d["tenant_id"]),
        name=d["name"],
        employee_id=d.get("employee_id"),
        role=d["role"],
        is_admin=bool(d["is_admin"]),
        language=d["language"],
    )
    tenant = {"id": str(tenant_raw["id"]), "name": tenant_raw["name"], "slug": tenant_raw["slug"]}
    return user, tenant


def get_current_user(request: Request) -> CurrentUser:
    """Read Authorization: Bearer <token>, verify it, load the profile."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise ApiError(401, "unauthorized", "Sign in to continue.")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise ApiError(401, "unauthorized", "Sign in to continue.")

    settings = request.app.state.settings
    claims = _verify_token(token, settings)
    user_id = claims.get("sub")
    if not user_id:
        raise ApiError(401, "invalid_token", "Session expired. Please sign in again.")
    user = load_profile(user_id)
    request.state.user_id = user.id  # for the JSON access log
    return user


def require_role(*roles: str):
    """Dependency factory: allow only the given roles."""

    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise ApiError(403, "forbidden_role", "You don't have access to this area.")
        return user

    return _dep


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise ApiError(403, "admin_only", "Only supervisors with admin access can do this.")
    return user
