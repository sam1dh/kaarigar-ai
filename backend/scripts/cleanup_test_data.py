"""Remove test data before the demo / production. DRY RUN by default: shows what it would delete.

    cd backend && python scripts/cleanup_test_data.py --plant shree                    # dry run
    cd backend && python scripts/cleanup_test_data.py --plant shree --apply            # delete

What counts as test data (all inside ONE plant):
  * people whose employee ID starts with --people-prefix (default TEST-) or whose name contains "[test]",
    plus everything they created: questions, feedback, escalations, repair notes, their logins in Supabase Auth
  * machines whose code starts with --machine-prefix (default TEST-), with their questions, notes and history
  * questions stuck as cancelled/failed older than --stale-days (default 2)
Never touches other plants, approved notes of real people, documents or breakdown logs of real machines.
Runs in one transaction: all or nothing. Prints counts only, never names or text.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def load_dotenv() -> None:
    for p in (Path(".env"), Path("../.env")):
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.split(" #")[0].strip().strip('"').strip("'"))
            return


PLAN = [
    # (label, SQL using temp tables _users/_machines)
    ("feedback", "delete from feedback where tenant_id = %(t)s and (user_id in (select id from _users) or query_id in (select id from _queries))"),
    ("escalations", "delete from escalations where tenant_id = %(t)s and query_id in (select id from _queries)"),
    ("search chunks of notes", "delete from chunks where tenant_id = %(t)s and source_type = 'record' and source_id in (select id from _records)"),
    ("search chunks of history", "delete from chunks where tenant_id = %(t)s and source_type = 'log' and machine_id in (select id from _machines)"),
    ("repair notes", "delete from repair_records where tenant_id = %(t)s and id in (select id from _records)"),
    ("questions", "delete from queries where tenant_id = %(t)s and id in (select id from _queries)"),
    ("breakdown history", "delete from maintenance_logs where tenant_id = %(t)s and machine_id in (select id from _machines)"),
    ("machines", "delete from machines where tenant_id = %(t)s and id in (select id from _machines)"),
    ("admin log entries", "delete from admin_audit where tenant_id = %(t)s and (actor_id in (select id from _users) or target_id in (select id from _users) or target_id in (select id from _machines))"),
    ("people", "delete from users where tenant_id = %(t)s and id in (select id from _users)"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plant", required=True, help="plant slug, e.g. shree")
    ap.add_argument("--people-prefix", default="TEST-")
    ap.add_argument("--machine-prefix", default="TEST-")
    ap.add_argument("--stale-days", type=int, default=2)
    ap.add_argument("--apply", action="store_true", help="really delete (default is a dry run)")
    a = ap.parse_args()
    if len(a.people_prefix) < 3 or len(a.machine_prefix) < 3:
        print("Prefixes must be at least 3 characters, so real people/machines can't match by accident.")
        return 2
    load_dotenv()
    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        row = conn.execute("select id from tenants where slug = %s", (a.plant,)).fetchone()
        if not row:
            print(f"No plant with slug '{a.plant}'.")
            return 2
        p = {"t": row[0], "pp": a.people_prefix.upper() + "%", "mp": a.machine_prefix.upper() + "%", "d": a.stale_days}
        conn.execute("""create temp table _users on commit drop as
                        select id from users where tenant_id = %(t)s and not is_admin
                          and (upper(employee_id) like %(pp)s or name ilike '%%[test]%%')""", p)
        conn.execute("create temp table _machines on commit drop as select id from machines where tenant_id = %(t)s and upper(code) like %(mp)s", p)
        conn.execute("""create temp table _queries on commit drop as
                        select id from queries where tenant_id = %(t)s and (user_id in (select id from _users)
                          or machine_id in (select id from _machines)
                          or (status in ('cancelled', 'failed') and created_at < now() - make_interval(days => %(d)s)))""", p)
        conn.execute("""create temp table _records on commit drop as
                        select id from repair_records where tenant_id = %(t)s and (author_id in (select id from _users)
                          or machine_id in (select id from _machines))""", p)
        # a real person's note that answered a test escalation keeps existing; just unlink it
        conn.execute("""update repair_records set escalation_id = null where tenant_id = %(t)s and escalation_id in
                        (select id from escalations where query_id in (select id from _queries))
                        and id not in (select id from _records)""", p)
        # real rows that merely point at a test person: clear the pointer, keep the row
        for sql in ("update escalations set assigned_to = null, assigned_at = null where tenant_id = %(t)s and assigned_to in (select id from _users)",
                    "update escalations set replied_by = null where tenant_id = %(t)s and replied_by in (select id from _users)",
                    "update escalations set asked_by = null where tenant_id = %(t)s and asked_by in (select id from _users)",
                    "update repair_records set reviewed_by = null where tenant_id = %(t)s and reviewed_by in (select id from _users)",
                    "update repair_records set archived_by = null where tenant_id = %(t)s and archived_by in (select id from _users)",
                    "update users set created_by = null where tenant_id = %(t)s and created_by in (select id from _users)",
                    "update escalations set machine_id = null where tenant_id = %(t)s and machine_id in (select id from _machines)"):
            conn.execute(sql, p)
        user_ids = [str(r[0]) for r in conn.execute("select id from _users").fetchall()]
        print(f"Plant '{a.plant}' — {'DELETING' if a.apply else 'dry run, nothing deleted'}")
        for label, sql in PLAN:
            if a.apply:
                n = conn.execute(sql, p).rowcount
            else:
                n = conn.execute(f"select count(*) from ({sql.replace('delete from', 'select 1 from', 1)}) x", p).fetchone()[0]
            print(f"  {label:<26} {n}")
        print(f"  {'logins (Supabase Auth)':<26} {len(user_ids)}")
        if not a.apply:
            conn.rollback()
            print("\nRun again with --apply to delete.")
            return 0
        conn.commit()

    if user_ids:
        from app.manage.auth_admin import AuthAdminError, GoTrueAdmin

        g = GoTrueAdmin(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
        gone = 0
        for uid in user_ids:
            try:
                g.delete_user(uid)
                gone += 1
            except AuthAdminError as e:
                print(f"  couldn't delete one login ({e.code}); remove it in Supabase → Authentication")
        print(f"  logins deleted: {gone}/{len(user_ids)}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
