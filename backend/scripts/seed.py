"""Seed the demo plant (Shree Hydraulics) — idempotent, safe to run twice.

Creates:
  - tenant 'shree' (Shree Hydraulics, Pune)
  - 3 machine models, 4 machines (with QR tokens)
  - 3 technician/expert auth users (hidden email + PIN) + users rows
  - 1 supervisor (real email + SEED_ADMIN_PASSWORD)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import get_settings
from app.core.supabase import admin_client

PLANT = {"name": "Shree Hydraulics", "slug": "shree", "city": "Pune"}

MODELS = [
    {"model": "HPX-200", "type": "hydraulic press", "oem": "Generic Hydraulics"},
    {"model": "CL-40", "type": "cnc lathe", "oem": "Generic CNC"},
    {"model": "AC-75", "type": "air compressor", "oem": "Generic Air"},
]

MACHINES = [
    {"code": "HP-07", "name": "Hydraulic press", "line": "Line 2", "model": "HPX-200"},
    {"code": "HP-02", "name": "Hydraulic press", "line": "Line 2", "model": "HPX-200"},
    {"code": "CNC-03", "name": "CNC lathe", "line": "Line 1", "model": "CL-40"},
    {"code": "AC-01", "name": "Air compressor", "line": "Line 3", "model": "AC-75"},
]

USERS = [
    # (name, employee_id, role, is_admin, language, pin)
    ("Amit Kale", "SH-0412", "technician", False, "hi-IN", "482913"),
    ("Priya Shinde", "SH-0233", "technician", False, "mr-IN", "735104"),
    ("Ramesh Patil", "SH-0107", "expert", False, "mr-IN", "261847"),
]


def main() -> None:
    settings = get_settings()
    db = admin_client()

    # --- Tenant ---------------------------------------------------------
    tenant = db.table("tenants").select("id").eq("slug", PLANT["slug"]).limit(1).execute()
    if tenant.data:
        tenant_id = tenant.data[0]["id"]
        print(f"Plant '{PLANT['slug']}' already exists.")
    else:
        tenant_id = (
            db.table("tenants")
            .insert({"name": PLANT["name"], "slug": PLANT["slug"], "city": PLANT["city"]})
            .execute()
            .data[0]["id"]
        )
        print(f"Created plant {PLANT['name']} ({PLANT['slug']}).")

    # --- Machine models ---------------------------------------------------
    model_ids: dict[str, str] = {}
    for m in MODELS:
        row = (
            db.table("machine_models")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("model", m["model"])
            .limit(1)
            .execute()
        )
        if row.data:
            model_ids[m["model"]] = row.data[0]["id"]
        else:
            new = db.table("machine_models").insert({"tenant_id": tenant_id, **m}).execute().data[0]
            model_ids[m["model"]] = new["id"]
    print(f"Machine models ready: {', '.join(model_ids)}")

    # --- Machines ---------------------------------------------------------
    machine_rows: list[dict] = []
    for m in MACHINES:
        row = (
            db.table("machines")
            .select("id, code, name, line, qr_token")
            .eq("tenant_id", tenant_id)
            .eq("code", m["code"])
            .limit(1)
            .execute()
        )
        if row.data:
            machine_rows.append(row.data[0])
        else:
            new = (
                db.table("machines")
                .insert(
                    {
                        "tenant_id": tenant_id,
                        "model_id": model_ids[m["model"]],
                        "code": m["code"],
                        "name": m["name"],
                        "line": m["line"],
                    }
                )
                .execute()
                .data[0]
            )
            machine_rows.append(new)

    # --- Users --------------------------------------------------------------
    for name, employee_id, role, is_admin, language, pin in USERS:
        email = settings.employee_email(employee_id, PLANT["slug"])
        profile = (
            db.table("users")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("employee_id", employee_id)
            .limit(1)
            .execute()
        )
        if profile.data:
            print(f"User {name} ({employee_id}) already exists.")
            continue
        auth_user = db.auth.admin.create_user(
            {
                "email": email,
                "password": pin,
                "email_confirm": True,
                "user_metadata": {"name": name},
            }
        )
        db.table("users").insert(
            {
                "id": auth_user.user.id,
                "tenant_id": tenant_id,
                "name": name,
                "employee_id": employee_id,
                "role": role,
                "is_admin": is_admin,
                "language": language,
            }
        ).execute()
        print(f"Created {role} {name} — sign in {employee_id} / PIN {pin}")

    # --- Supervisor (email + password) --------------------------------------
    supervisor_email = "suresh@shreehydraulics.in"
    profile = (
        db.table("users")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("role", "supervisor")
        .limit(1)
        .execute()
    )
    if not profile.data:
        password = settings.seed_admin_password or "changeme-supervisor"
        auth_user = db.auth.admin.create_user(
            {
                "email": supervisor_email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"name": "Suresh Kulkarni"},
            }
        )
        db.table("users").insert(
            {
                "id": auth_user.user.id,
                "tenant_id": tenant_id,
                "name": "Suresh Kulkarni",
                "employee_id": None,
                "role": "supervisor",
                "is_admin": True,
                "language": "hi-IN",
            }
        ).execute()
        print(
            f"Created supervisor Suresh Kulkarni — {supervisor_email} / password from SEED_ADMIN_PASSWORD"
        )
    else:
        print("Supervisor already exists.")

    # --- Report ---------------------------------------------------------
    machine_rows.sort(key=lambda m: m["code"])
    print("\nMachines and their QR tokens:")
    print(f"  {'code':<8} {'name':<18} {'line':<8} qr_token")
    for m in machine_rows:
        print(f"  {m['code']:<8} {m['name'] or '':<18} {m['line'] or '':<8} {m['qr_token']}")

    print("\nDemo logins:")
    print("  Phone:  SH-0412 / 482913 (Amit Kale, technician)")
    print("          SH-0233 / 735104 (Priya Shinde, technician)")
    print("          SH-0107 / 261847 (Ramesh Patil, expert)")
    print(
        f"  Web:    {supervisor_email} / <SEED_ADMIN_PASSWORD> (Suresh Kulkarni, supervisor · admin)"
    )


if __name__ == "__main__":
    main()
