"""Run supabase/migrations/*.sql against the Supabase Postgres DB in order.

Usage (from backend/): .venv/bin/python scripts/run_migrations.py
Idempotent per migration: each file runs once, tracked in _migrations.
"""

from __future__ import annotations

import os
import sys

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIGRATIONS_DIR = os.path.join(REPO_ROOT, "supabase", "migrations")


def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        # load .env from repo root
        from dotenv import load_dotenv

        load_dotenv(os.path.join(REPO_ROOT, ".env"))
        url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set")
        sys.exit(1)

    conn = psycopg.connect(url, sslmode="require")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "create table if not exists _migrations (name text primary key, applied_at timestamptz default now())"
        )

        for name in sorted(os.listdir(MIGRATIONS_DIR)):
            if not name.endswith(".sql"):
                continue
            cur.execute("select 1 from _migrations where name = %s", (name,))
            if cur.fetchone():
                print(f"skip {name} (already applied)")
                continue
            path = os.path.join(MIGRATIONS_DIR, name)
            print(f"applying {name} …")
            with open(path, encoding="utf-8") as f:
                sql = f.read()
            try:
                cur.execute(sql)
            except Exception as e:
                print(f"FAILED {name}: {e}")
                raise
            cur.execute("insert into _migrations (name) values (%s)", (name,))
            print(f"ok {name}")
    conn.close()
    print("migrations complete")


if __name__ == "__main__":
    main()
