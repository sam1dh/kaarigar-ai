"""Auth endpoints: PIN login (technicians/experts) and the current profile.

Latency notes: every call here is a READ. The endpoint is fast because it makes
as few sequential HTTPS round-trips to Supabase (Mumbai) as possible:
  - POST /auth/pin-login = 1 auth call (bcrypt, deliberately slow) + 1 combined
    profile+tenant query (PostgREST embedding).
  - GET /auth/me = 1 combined profile+tenant query.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends
from supabase import AuthApiError

from app.core.auth import CurrentUser, get_current_user, load_profile_with_tenant
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.supabase import anon_client
from app.schemas import PinLoginRequest, PinLoginResponse, ProfileOut

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("kaarigar.auth")

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
        auth = anon_client().auth.sign_in_with_password({"email": email, "password": body.pin})
    except AuthApiError as exc:
        _record_failure(rl_key)
        # Log only the exception class, never the attempted credentials.
        logger.info("pin_login failed for %s: %s", rl_key, exc.__class__.__name__)
        raise ApiError(401, "invalid_login", "Wrong employee ID or PIN. Please try again.") from exc

    session = auth.session
    if session is None:  # pragma: no cover — password sign-in always returns a session
        raise ApiError(401, "invalid_login", "Wrong employee ID or PIN. Please try again.")

    # The token was just issued by Supabase, so loading the profile by user id is safe.
    user, tenant = load_profile_with_tenant(session.user.id)
    return PinLoginResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token or "",
        expires_in=session.expires_in or 3600,
        profile=_profile_out(user, tenant),
    )


@router.get("/me", response_model=ProfileOut)
def me(user: CurrentUser = Depends(get_current_user)) -> ProfileOut:
    _, tenant = load_profile_with_tenant(user.id)
    return _profile_out(user, tenant)
