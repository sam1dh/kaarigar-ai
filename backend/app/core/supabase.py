"""Supabase clients: admin (service role, bypasses RLS) and anon (for password sign-in)."""

from functools import lru_cache

from supabase import Client, create_client

from app.core.config import get_settings


@lru_cache
def admin_client() -> Client:
    """Service-role client. Never expose its key to the frontend."""
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_role_key)


@lru_cache
def anon_client() -> Client:
    """Anon-key client, used only for auth sign-in calls."""
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_anon_key)
