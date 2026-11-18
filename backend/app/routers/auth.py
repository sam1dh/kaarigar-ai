"""Auth endpoints: PIN login (technicians/experts) and the current profile.

Latency notes: POST /auth/pin-login and GET /auth/me are reads, kept fast by
making as few sequential HTTPS round-trips to Supabase (Mumbai) as possible:
  - POST /auth/pin-login = 1 auth call (bcrypt, deliberately slow) + 1 combined
    profile+tenant query (PostgREST embedding).
  - GET /auth/me = 1 combined profile+tenant query.
PATCH /auth/me is the only write here (saves the chosen language).
"""

from __future__ import annotations

import logging
import time

import httpx
from fastapi import APIRouter, Depends

from app.core.auth import (
    CurrentUser,
    cache_profile,
    get_current_user,
    load_profile_with_tenant,
    preload_profiles,
    warm_jwks,
)
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.languages import is_enabled
from app.core.supabase import admin_client
from app.schemas import LanguageUpdate, PinLoginRequest, PinLoginResponse, ProfileOut

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("kaarigar.auth")

# One keep-alive client for password sign-in, process-wide. Reusing the TCP/TLS
# connection removes ~200-400 ms of handshake from every PIN login. We call the
# token endpoint directly (not supabase-py) because supabase-py stores the signed-in
# session on its Client, and a shared client would leak sessions between users.
_http = httpx.Client(
    timeout=15.0,
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10, keepalive_expiry=60.0),
)

# Simple in-memory rate limit: 5 failed tries per employee per 5 minutes.
FAILED_TRIES_LIMIT = 5
FAILED_TRIES_WINDOW = 300  # seconds
_failed_tries: dict[str, list[float]] = {}


def _rate_limited(key: str) -> bool:
    now = time.time()
    tries = [t for t in _failed_tries.get(key, []) if now - t < FAILED_TRIES_WINDOW]
    _failed_tries[key] = tries
    return len(tries) >= FAILED_TRIES_LIMIT


def _record_failure(key: str) -> None:
    _failed_tries.setdefault(key, []).append(time.time())


def _profile_out(user: CurrentUser, tenant: dict) -> ProfileOut:
    return ProfileOut(
        id=user.id,
        name=user.name,
        employee_id=user.employee_id,
        role=user.role,
        is_admin=user.is_admin,
        language=user.language,
        tenant=tenant,
    )


@router.post("/pin-login", response_model=PinLoginResponse)
def pin_login(body: PinLoginRequest) -> PinLoginResponse:
    settings = get_settings()
    plant_slug = body.plant_code.strip().lower()

    # The hidden email embeds the plant slug, so a wrong plant code simply fails
    # auth below — no separate tenant lookup needed (saves one round-trip).
    email = settings.employee_email(body.employee_id.strip(), plant_slug)
    rl_key = email.lower()

    if _rate_limited(rl_key):
        raise ApiError(429, "too_many_attempts", "Too many tries. Ask your supervisor to help.")

    try:
        t0 = time.perf_counter()
        resp = _http.post(
            f"{settings.supabase_url}/auth/v1/token",
            params={"grant_type": "password"},
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {settings.supabase_anon_key}",
            },
            json={"email": email, "password": body.pin},
        )
        t_auth = int((time.perf_counter() - t0) * 1000)
        if resp.status_code >= 400:
            raise ValueError(f"auth_status_{resp.status_code}")
        session = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        _record_failure(rl_key)
        # Log only the exception class/status, never the attempted credentials.
        logger.info("pin_login failed for %s: %s", rl_key, exc.__class__.__name__)
        raise ApiError(401, "invalid_login", "Wrong employee ID or PIN. Please try again.") from exc

    user_id = (session.get("user") or {}).get("id")
    if not user_id:  # pragma: no cover — password sign-in always returns a user
        raise ApiError(401, "invalid_login", "Wrong employee ID or PIN. Please try again.")

    # The token was just issued by Supabase, so loading the profile by user id is safe.
    t1 = time.perf_counter()
    user, tenant = load_profile_with_tenant(user_id)
    t_profile = int((time.perf_counter() - t1) * 1000)
    total = int((time.perf_counter() - t0) * 1000)
    logger.info(
        "pin_login ok (%s): auth %d ms, profile %d ms, total %d ms",
        plant_slug, t_auth, t_profile, total,
    )
    return PinLoginResponse(
        access_token=session["access_token"],
        refresh_token=session.get("refresh_token") or "",
        expires_in=session.get("expires_in") or 3600,
        profile=_profile_out(user, tenant),
    )


@router.get("/me", response_model=ProfileOut)
def me(user: CurrentUser = Depends(get_current_user)) -> ProfileOut:
    # get_current_user already fetched profile + tenant in one query.
    return _profile_out(user, user.tenant or {})


@router.patch("/me", response_model=ProfileOut)
def update_me(body: LanguageUpdate, user: CurrentUser = Depends(get_current_user)) -> ProfileOut:
    # Only enabled codes from shared/languages.json are allowed.
    if not is_enabled(body.language):
        raise ApiError(422, "unsupported_language", "This language isn't available yet.")
    admin_client().table("users").update({"language": body.language}).eq("id", user.id).execute()
    user.language = body.language
    tenant = user.tenant or {}
    # Keep the hot cache in sync so the next /auth/me does not re-query Supabase.
    cache_profile(user, tenant)
    return _profile_out(user, tenant)


def warm_connections() -> None:
    """Open the Supabase TLS/keep-alive connections at startup.

    The first PIN login on a cold process otherwise pays for two TLS handshakes
    (Auth and PostgREST) on top of bcrypt. Warming both in the background removes
    that cost from the user's first login without delaying readiness.
    """
    settings = get_settings()
    if not settings.supabase_url:
        return
    try:
        _http.get(
            f"{settings.supabase_url}/auth/v1/health",
            headers={"apikey": settings.supabase_anon_key},
            timeout=5.0,
        )
    except Exception:  # noqa: BLE001 - best effort, never block startup
        logger.debug("auth connection prewarm skipped", exc_info=True)
    try:
        warm_jwks(settings)
    except Exception:  # noqa: BLE001
        logger.debug("jwks prewarm skipped", exc_info=True)
    try:
        preload_profiles()
    except Exception:  # noqa: BLE001
        logger.debug("profile preload skipped", exc_info=True)
