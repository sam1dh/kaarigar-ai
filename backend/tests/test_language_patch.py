"""PATCH /auth/me (language update) — needs a real Supabase project when env is present.

Checks from PHASE_0.md section 10:
  - enabled code  → 200
  - "as-IN" (disabled) → 422 unsupported_language
  - no token → 401
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ENABLED_CODE = "ta-IN"  # Karthik's language — enabled in shared/languages.json
DISABLED_CODE = "as-IN"  # Assamese — disabled in Phase 0
AMIT_EMAIL = "sh-0412@shree.employees.kaarigar.app"
AMIT_PIN = "482913"
AMIT_ORIGINAL_LANGUAGE = "hi-IN"


def _get_token() -> str | None:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not (url and key):
        return None
    import httpx

    resp = httpx.post(
        f"{url}/auth/v1/token?grant_type=password",
        headers={"apikey": key, "Content-Type": "application/json"},
        json={"email": AMIT_EMAIL, "password": AMIT_PIN},
        timeout=15,
    )
    if resp.status_code != 200:
        return None
    return resp.json()["access_token"]


def test_patch_language_no_token_401() -> None:
    resp = client.patch("/auth/me", json={"language": ENABLED_CODE})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


@pytest.mark.skipif(_get_token() is None, reason="SUPABASE_URL/ANON_KEY not configured")
def test_patch_language_enabled_and_disabled() -> None:
    token = _get_token()
    assert token
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # Disabled code → 422 unsupported_language
        resp = client.patch("/auth/me", json={"language": DISABLED_CODE}, headers=headers)
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "unsupported_language"

        # Enabled code → 200 and saved
        resp = client.patch("/auth/me", json={"language": ENABLED_CODE}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["language"] == ENABLED_CODE
        assert body["name"] == "Amit Kale"

        # GET /auth/me reflects the saved language
        resp = client.get("/auth/me", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["language"] == ENABLED_CODE
    finally:
        # Restore Amit's original language so other checks aren't affected.
        client.patch("/auth/me", json={"language": AMIT_ORIGINAL_LANGUAGE}, headers=headers)
