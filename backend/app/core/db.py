"""psycopg pool for vector queries (supabase-py can't run vector searches).

The backend connects with the privileged DATABASE_URL, so RLS does NOT protect
these queries — every service must filter tenant_id explicitly.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg_pool import ConnectionPool

logger = logging.getLogger("kaarigar.db")

_pool: ConnectionPool | None = None


def _dsn() -> str:
    # Settings load DATABASE_URL from .env, but this module is also imported by
    # scripts that only export the variable. Accept either source.
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        from app.core.config import get_settings

        url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set (checked environment and .env).")
    # Session pooler URLs sometimes lack sslmode; Supabase requires TLS.
    if "sslmode" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def _configure(conn: Connection) -> None:
    """Run on every new pooled connection: vector type + a good hnsw ef_search."""
    register_vector(conn)
    conn.execute("set hnsw.ef_search = 100")
    conn.commit()


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            _dsn(),
            min_size=1,
            max_size=3,  # Supabase free session pooler: keep the total (capture uses 2) small
            timeout=10,  # fail fast on checkout instead of hanging 30 s
            open=True,
            configure=_configure,
            kwargs={"autocommit": False},
        )
    return _pool


@contextmanager
def db() -> Connection:
    """Borrow a pooled connection. Use as a transaction: commit on success."""
    pool = get_pool()
    with pool.connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


@contextmanager
def db_read() -> Connection:
    """Read-only fast path: autocommit (no BEGIN/COMMIT round trips).

    Restores autocommit=False before the connection returns to the pool.
    """
    pool = get_pool()
    with pool.connection() as conn:
        conn.autocommit = True
        try:
            yield conn
        finally:
            conn.autocommit = False


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
