"""Checks before the first production deploy (Phase 5). Read-only: changes nothing.

    cd backend && python scripts/predeploy_check.py              # env + database checks
    cd backend && python scripts/predeploy_check.py --online     # also pings Groq, Sarvam and Supabase Auth

Reads the same environment as the app (.env or real env vars). Prints PASS / WARN / FAIL per check and
never prints a secret. Exit code 1 if anything FAILs.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
from pathlib import Path

RESULTS: list[tuple[str, str, str]] = []


def report(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name}{' — ' + detail if detail else ''}")


def load_dotenv() -> None:
    for p in (Path(".env"), Path("../.env")):
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.split(" #")[0].strip().strip('"').strip("'"))
            return


def jwt_role(token: str) -> str | None:
    """Role claim of a legacy Supabase key (anon / service_role). New sb_secret_/sb_publishable_ keys have none."""
    if token.startswith("sb_secret_"):
        return "service_role"
    if token.startswith("sb_publishable_"):
        return "anon"
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("role")
    except Exception:  # noqa: BLE001
        return None


def check_env() -> None:
    env = os.environ
    required = ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "DATABASE_URL", "GROQ_API_KEY",
                "SARVAM_API_KEY", "PUBLIC_APP_URL", "ALLOWED_ORIGINS", "EMPLOYEE_EMAIL_DOMAIN"]
    missing = [k for k in required if not env.get(k)]
    report("FAIL" if missing else "PASS", "Required settings", f"missing: {', '.join(missing)}" if missing else "all set")

    report("PASS" if env.get("APP_ENV") == "production" else "FAIL", "APP_ENV=production", "hides /dev/* routes")

    role = jwt_role(env.get("SUPABASE_SERVICE_ROLE_KEY", ""))
    report("PASS" if role == "service_role" else "FAIL", "SUPABASE_SERVICE_ROLE_KEY is the service key",
           "" if role == "service_role" else f"looks like '{role}'")
    arole = jwt_role(env.get("SUPABASE_ANON_KEY", ""))
    report("PASS" if arole in ("anon", None) else "FAIL", "SUPABASE_ANON_KEY is not a service key")

    leaked = [k for k, v in env.items() if k.startswith("VITE_") and v and (
        v == env.get("SUPABASE_SERVICE_ROLE_KEY") or v in (env.get("GROQ_API_KEY"), env.get("SARVAM_API_KEY")) or jwt_role(v) == "service_role")]
    report("FAIL" if leaked else "PASS", "No secrets in VITE_* variables", ", ".join(leaked))

    url = env.get("PUBLIC_APP_URL", "")
    ok = url.startswith("https://") and "localhost" not in url and "trycloudflare" not in url and not url.endswith("/")
    report("PASS" if ok else "FAIL", "PUBLIC_APP_URL is the final https app address",
           "it is printed in every QR sticker; changing it later means reprinting" if ok else url or "empty")

    origins = [o.strip() for o in env.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    bad = [o for o in origins if o == "*" or "localhost" in o or "127.0.0.1" in o or not o.startswith("https://")]
    report("WARN" if bad else "PASS", "ALLOWED_ORIGINS only production https origins", ", ".join(bad))

    db = env.get("DATABASE_URL", "")
    report("PASS" if ("sslmode=require" in db or "sslmode=verify" in db) else "WARN", "DATABASE_URL uses sslmode=require")
    report("PASS" if ":6543" in db or "pooler" in db else "WARN", "DATABASE_URL goes through the Supabase pooler",
           "direct 5432 connections run out fast on small plans")

    lf = Path(env.get("LANGUAGES_FILE") or Path(__file__).resolve().parents[2] / "shared" / "languages.json")
    report("PASS" if lf.exists() else "FAIL", "languages.json found", str(lf))

    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        report("PASS", "ffmpeg available", Path(exe).name)
    except Exception:  # noqa: BLE001
        report("PASS" if shutil.which("ffmpeg") else "FAIL", "ffmpeg available")

    try:
        import segno  # noqa: F401
        report("PASS", "segno installed (QR stickers)")
    except ImportError:
        report("FAIL", "segno installed (QR stickers)", "pip install -r requirements-phase4.txt")


SQL_CHECKS = [
    ("Phase 0-1 tables", "select count(*) from information_schema.tables where table_schema='public' and table_name = any(%s)",
     (["tenants", "users", "machines", "machine_models", "documents", "chunks", "maintenance_logs", "log_imports",
       "repair_records", "queries", "feedback", "escalations"],), 12),
    ("Migration 0004 (Phase 3)", "select count(*) from information_schema.columns where table_name='queries' and column_name in ('status','answer_local','first_token_ms')", (), 3),
    ("Migration 0005 (Phase 4)", "select count(*) from information_schema.columns where (table_name, column_name) in (('users','deactivated_at'),('machines','archived_at'),('repair_records','archived_at'))", (), 3),
    ("admin_audit table", "select count(*) from information_schema.tables where table_name='admin_audit'", (), 1),
]


def check_db() -> None:
    try:
        import psycopg
    except ImportError:
        report("FAIL", "psycopg installed")
        return
    try:
        conn = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=8)
    except Exception as e:  # noqa: BLE001
        report("FAIL", "Database reachable", type(e).__name__)
        return
    report("PASS", "Database reachable")
    with conn:
        for name, sql, params, want in SQL_CHECKS:
            n = conn.execute(sql, params).fetchone()[0]
            report("PASS" if n >= want else "FAIL", name, f"{n}/{want}")
        no_rls = [r[0] for r in conn.execute(
            """select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
               where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity""").fetchall()]
        report("FAIL" if no_rls else "PASS", "Row level security on every public table", ", ".join(no_rls))
        try:
            pub = [r[0] for r in conn.execute("select id from storage.buckets where public").fetchall()]
            report("FAIL" if pub else "PASS", "Storage buckets are private", ", ".join(pub))
        except Exception:  # noqa: BLE001
            conn.rollback()
            report("WARN", "Storage buckets are private", "couldn't read storage.buckets; check in the dashboard")
        exposed = conn.execute("select count(*) from information_schema.schemata where schema_name in ('langgraph')").fetchone()[0]
        report("PASS" if exposed else "WARN", "LangGraph schema present (keep it out of Data API exposed schemas)")
        admins = conn.execute("select count(*) from users where is_admin and role='supervisor' and deactivated_at is null").fetchone()[0]
        report("PASS" if admins else "FAIL", "At least one active plant admin", str(admins))
        machines = conn.execute("select count(*) from machines where archived_at is null").fetchone()[0]
        unprinted = conn.execute("select count(*) from machines where archived_at is null and sticker_printed_at is null").fetchone()[0]
        report("PASS" if machines else "WARN", "Machines set up", f"{machines} active, {unprinted} without printed stickers")
        tests = conn.execute("select count(*) from users where employee_id ilike 'TEST-%%' or name ilike '%%[test]%%'").fetchone()[0]
        report("WARN" if tests else "PASS", "No test people left", f"{tests} found: run scripts/cleanup_test_data.py" if tests else "")


def check_online() -> None:
    import httpx

    env = os.environ
    for name, req in [
        ("Supabase Auth admin reachable", lambda c: c.get(f"{env['SUPABASE_URL'].rstrip('/')}/auth/v1/admin/users?per_page=1",
                                                       headers={"apikey": env["SUPABASE_SERVICE_ROLE_KEY"], "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}"})),
        ("Groq key works", lambda c: c.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {env['GROQ_API_KEY']}"})),
    ]:
        try:
            with httpx.Client(timeout=10) as c:
                r = req(c)
            report("PASS" if r.status_code == 200 else "FAIL", name, f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            report("FAIL", name, type(e).__name__)
    report("WARN", "Sarvam key", "not pinged (every call costs); ask one voice question on staging instead")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--online", action="store_true", help="also call Supabase Auth and Groq")
    ap.add_argument("--no-db", action="store_true")
    a = ap.parse_args()
    load_dotenv()
    print("Kaarigar pre-deploy check\n")
    check_env()
    if not a.no_db:
        check_db()
    if a.online:
        check_online()
    fails = sum(1 for s, *_ in RESULTS if s == "FAIL")
    warns = sum(1 for s, *_ in RESULTS if s == "WARN")
    print(f"\n{len(RESULTS)} checks: {fails} FAIL, {warns} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
