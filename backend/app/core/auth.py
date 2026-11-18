"""Supabase JWT verification and role dependencies."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, replace

import jwt
from fastapi import Depends, Request

from app.core.errors import ApiError
from app.core.supabase import admin_client

logger = logging.getLogger("kaarigar.auth")

_CACHE_TTL = 300  # seconds

# Small profile cache. Every authenticated request otherwise costs a PostgREST
# round-trip (~150-225 ms from the campus network). The profile only changes when
# the user edits their language or an admin edits the user, so a 5 min cache keeps
# `/auth/me` fast; PATCH /auth/me refreshes the entry immediately. Keyed by auth user id.
_PROFILE_TTL = 300.0
_profile_cache: dict[str, tuple[float, CurrentUser, dict]] = {}
_profile_lock = threading.Lock()


def cache_profile(user: CurrentUser, tenant: dict) -> None:
    """Remember a freshly loaded profile (called by login and PATCH /auth/me)."""
    with _profile_lock:
        _profile_cache[user.id] = (time.time() + _PROFILE_TTL, replace(user), dict(tenant))


@dataclass
class CurrentUser:
    id: str
    tenant_id: str
    name: str
    employee_id: str | None
    role: str
    is_admin: bool
    language: str
    tenant: dict | None = None  # loaded once with the profile (name, slug)


# ---- JWKS (cached for _CACHE_TTL) ----
_jwk_client: jwt.PyJWKClient | None = None


def _get_jwk_client(jwks_url: str) -> jwt.PyJWKClient:
    """One client per process; the JWKS (token signing keys) is fetched once and
    cached in memory (cache_keys=True, refreshed after _CACHE_TTL) — never
    downloaded per request."""
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=_CACHE_TTL)
    return _jwk_client


def warm_jwks(settings) -> None:
    """Fetch and cache the signing keys so the first authenticated request does not."""
    if settings.supabase_jwt_secret:
        return
    jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    _get_jwk_client(jwks_url).fetch_data()
    logger.info("jwks preloaded")


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


def preload_profiles(limit: int = 5000) -> int:
    """Warm the profile cache with every user in one query.

    The first login on a cold process otherwise waits ~0.5-0.7 s for its profile
    row (PostgREST/TLS warmup). This app has a small user table, so loading it
    once at startup turns the first PIN login's profile step into a cache hit.
    """
    rows = (
        admin_client()
        .table("users")
        .select(
            "id, tenant_id, name, employee_id, role, is_admin, language, tenant:tenants(id, name, slug)"
        )
        .limit(limit)
        .execute()
    )
    loaded = 0
    for d in rows.data or []:
        tenant_raw = d.get("tenant") or {}
        if not tenant_raw:
            continue
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
        cache_profile(user, tenant)
        loaded += 1
    logger.info("profile cache preloaded: %d users", loaded)
    return loaded


def load_profile_with_tenant(user_id: str) -> tuple[CurrentUser, dict]:
    """Profile + tenant in a single REST call (PostgREST embeds tenants via the FK).

    A short-lived cache avoids a network round-trip on every authenticated request
    and makes the profile loaded during PIN login immediately reusable by /auth/me.
    """
    now = time.time()
    with _profile_lock:
        hit = _profile_cache.get(user_id)
        if hit and hit[0] > now:
            return replace(hit[1]), dict(hit[2])

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
    cache_profile(user, tenant)
    return user, tenant


def get_current_user(request: Request) -> CurrentUser:
    """Read Authorization: Bearer <token>, verify it, load the profile (and tenant)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise ApiError(401, "unauthorized", "Sign in to continue.")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise ApiError(401, "unauthorized", "Sign in to continue.")

    settings = request.app.state.settings
    t0 = time.perf_counter()
    claims = _verify_token(token, settings)
    t_verify = int((time.perf_counter() - t0) * 1000)
    user_id = claims.get("sub")
    if not user_id:
        raise ApiError(401, "invalid_token", "Session expired. Please sign in again.")
    t1 = time.perf_counter()
    user, tenant = load_profile_with_tenant(user_id)
    t_profile = int((time.perf_counter() - t1) * 1000)
    logger.info(
        "auth ok: verify %d ms, profile %d ms, total %d ms",
        t_verify, t_profile, t_verify + t_profile,
    )
    user.tenant = tenant
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
