"""In-memory fakes so Phase 4 can be tested without Supabase."""
from __future__ import annotations

import copy
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from app.manage.auth_admin import AuthAdminError

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
SUPER = "aaaaaaaa-0000-0000-0000-000000000001"     # Suresh, supervisor + admin
SUPER2 = "aaaaaaaa-0000-0000-0000-000000000002"    # Meena, supervisor, not admin
AMIT = "aaaaaaaa-0000-0000-0000-000000000412"
RAMESH = "aaaaaaaa-0000-0000-0000-000000000107"
OTHER_ADMIN = "bbbbbbbb-0000-0000-0000-000000000001"
MODEL_HPX = "cccccccc-0000-0000-0000-000000000200"
HP07 = "dddddddd-0000-0000-0000-000000000007"
CNC03 = "dddddddd-0000-0000-0000-000000000003"
REC1 = "eeeeeeee-0000-0000-0000-000000000001"
REC_PENDING = "eeeeeeee-0000-0000-0000-000000000002"


def now():
    return datetime.now(timezone.utc)


class FakeAuth:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.fail: str | None = None          # e.g. "auth_unreachable"
        self.calls: list[tuple] = []

    def _maybe_fail(self):
        if self.fail:
            raise AuthAdminError(self.fail)

    def create_user(self, email, password, *, name=None):
        self.calls.append(("create", email))
        self._maybe_fail()
        if any(u["email"] == email for u in self.users.values()):
            raise AuthAdminError("login_exists", 422)
        uid = str(uuid.uuid4())
        self.users[uid] = {"email": email, "password": password, "blocked": False}
        return uid

    def set_password(self, user_id, password):
        self.calls.append(("set_password", user_id))
        self._maybe_fail()
        self.users.setdefault(user_id, {"email": None, "blocked": False})["password"] = password

    def set_blocked(self, user_id, blocked):
        self.calls.append(("set_blocked", user_id, blocked))
        self._maybe_fail()
        self.users.setdefault(user_id, {"email": None, "password": None})["blocked"] = blocked

    def delete_user(self, user_id):
        self.calls.append(("delete", user_id))
        self.users.pop(user_id, None)


class FakeRepo:
    def __init__(self):
        t0 = now() - timedelta(days=40)
        self.tenants = {TENANT: {"id": TENANT, "name": "Shree Hydraulics", "slug": "shree"},
                        OTHER: {"id": OTHER, "name": "Other", "slug": "other"}}
        self.users = {
            SUPER: dict(id=SUPER, tenant_id=TENANT, name="Suresh Kulkarni", employee_id=None, role="supervisor",
                        is_admin=True, language="hi-IN", created_at=t0, deactivated_at=None,
                        email="suresh@shreehydraulics.in", last_sign_in_at=now()),
            SUPER2: dict(id=SUPER2, tenant_id=TENANT, name="Meena Joshi", employee_id=None, role="supervisor",
                         is_admin=False, language="mr-IN", created_at=t0, deactivated_at=None,
                         email="meena@shreehydraulics.in", last_sign_in_at=None),
            AMIT: dict(id=AMIT, tenant_id=TENANT, name="Amit Kale", employee_id="SH-0412", role="technician",
                       is_admin=False, language="hi-IN", created_at=t0, deactivated_at=None,
                       email="sh-0412@shree.employees.kaarigar.app", last_sign_in_at=now() - timedelta(days=1)),
            RAMESH: dict(id=RAMESH, tenant_id=TENANT, name="Ramesh Patil", employee_id="SH-0107", role="expert",
                         is_admin=False, language="mr-IN", created_at=t0, deactivated_at=None,
                         email="sh-0107@shree.employees.kaarigar.app", last_sign_in_at=now()),
            OTHER_ADMIN: dict(id=OTHER_ADMIN, tenant_id=OTHER, name="Elsewhere", employee_id=None, role="supervisor",
                              is_admin=True, language="en-IN", created_at=t0, deactivated_at=None,
                              email="x@other.in", last_sign_in_at=None),
        }
        self.models = {MODEL_HPX: {"id": MODEL_HPX, "tenant_id": TENANT, "model": "HPX-200", "type": "hydraulic press",
                                   "oem": "Generic"}}
        self.machines = {
            HP07: dict(id=HP07, tenant_id=TENANT, code="HP-07", name="Hydraulic press", line="Line 2",
                       model_id=MODEL_HPX, qr_token="a" * 24, created_at=t0, archived_at=None, sticker_printed_at=now()),
            CNC03: dict(id=CNC03, tenant_id=TENANT, code="CNC-03", name="CNC lathe", line="Line 1",
                        model_id=None, qr_token="b" * 24, created_at=t0, archived_at=None, sticker_printed_at=None),
        }
        self.records = {
            REC1: dict(id=REC1, tenant_id=TENANT, machine_id=HP07, status="approved", archived_at=None,
                       fields={"symptom": "pressure not building", "fix": "reset relief valve"}),
            REC_PENDING: dict(id=REC_PENDING, tenant_id=TENANT, machine_id=HP07, status="pending", archived_at=None,
                              fields={}),
        }
        self.chunks = {REC1}            # records that have a search chunk
        self.audits: list[dict] = []
        self.fail_insert_person = False

    # tenant + audit
    def tenant(self, t):
        return copy.deepcopy(self.tenants.get(t))

    def audit(self, t, actor, action, target_type, target_id, detail=None):
        self.audits.append(dict(tenant_id=t, actor_id=actor, action=action, target_type=target_type,
                                target_id=target_id, detail=detail or {}, created_at=now()))

    def audit_list(self, t, limit):
        rows = [dict(a, id=str(uuid.uuid4()), actor_name=self.users.get(a["actor_id"], {}).get("name"))
                for a in self.audits if a["tenant_id"] == t]
        return list(reversed(rows))[:limit]

    # people
    def _person(self, u):
        return dict(u, last_question_at=None, last_note_at=None, approved_notes=0)

    def list_people(self, t):
        return [self._person(u) for u in self.users.values() if u["tenant_id"] == t]

    def get_person(self, t, uid):
        u = self.users.get(uid)
        return self._person(u) if u and u["tenant_id"] == t else None

    def employee_id_taken(self, t, e):
        return any(u["tenant_id"] == t and (u["employee_id"] or "").upper() == e.upper() for u in self.users.values())

    def insert_person(self, *, user_id, tenant_id, name, employee_id, role, is_admin, language, created_by):
        if self.fail_insert_person:
            raise RuntimeError("db down")
        self.users[user_id] = dict(id=user_id, tenant_id=tenant_id, name=name, employee_id=employee_id, role=role,
                                   is_admin=is_admin, language=language, created_at=now(), deactivated_at=None,
                                   email=None, last_sign_in_at=None)

    def update_person(self, t, uid, **cols):
        assert set(cols) <= {"name", "role", "language", "is_admin"}
        self.users[uid].update(cols)
        return 1

    def set_deactivated(self, t, uid, deactivated):
        self.users[uid]["deactivated_at"] = now() if deactivated else None
        return 1

    def active_admin_count(self, t):
        return sum(1 for u in self.users.values() if u["tenant_id"] == t and u["is_admin"]
                   and u["role"] == "supervisor" and not u["deactivated_at"])

    # machines
    def _machine(self, m):
        mm = self.models.get(m["model_id"]) or {}
        return dict(m, model=mm.get("model"), type=mm.get("type"), oem=mm.get("oem"), approved_records=0,
                    questions_30d=0, last_breakdown_date=None, last_breakdown_fault=None)

    def list_machines(self, t, include_archived):
        rows = [self._machine(m) for m in self.machines.values()
                if m["tenant_id"] == t and (include_archived or not m["archived_at"])]
        return sorted(rows, key=lambda r: (r["archived_at"] is not None, r["code"]))

    def get_machine(self, t, mid):
        m = self.machines.get(mid)
        return self._machine(m) if m and m["tenant_id"] == t else None

    def machine_codes(self, t):
        return [{"id": m["id"], "code": m["code"]} for m in self.machines.values() if m["tenant_id"] == t]

    def model_in_tenant(self, t, model_id):
        m = self.models.get(model_id)
        return m if m and m["tenant_id"] == t else None

    def find_model(self, t, model):
        return next((m for m in self.models.values() if m["tenant_id"] == t and m["model"].upper() == model.upper()), None)

    def insert_model(self, t, model, type_, oem):
        mid = str(uuid.uuid4())
        self.models[mid] = {"id": mid, "tenant_id": t, "model": model, "type": type_, "oem": oem}
        return self.models[mid]

    def insert_machine(self, t, code, name, line, model_id):
        mid = str(uuid.uuid4())
        self.machines[mid] = dict(id=mid, tenant_id=t, code=code, name=name, line=line, model_id=model_id,
                                  qr_token=secrets.token_hex(12), created_at=now(), archived_at=None,
                                  sticker_printed_at=None)
        return mid

    def update_machine(self, t, mid, **cols):
        self.machines[mid].update(cols)
        return 1

    def set_machine_archived(self, t, mid, archived):
        self.machines[mid]["archived_at"] = now() if archived else None
        return 1

    def renew_qr(self, t, mid):
        self.machines[mid].update(qr_token=secrets.token_hex(12), sticker_printed_at=None)
        return self.machines[mid]["qr_token"]

    def machines_by_ids(self, t, ids):
        rows = [self._machine(m) for m in self.machines.values() if m["tenant_id"] == t and m["id"] in ids]
        return sorted(rows, key=lambda r: r["code"])

    def mark_printed(self, t, ids):
        for i in ids:
            self.machines[i]["sticker_printed_at"] = now()
        return len(ids)

    # knowledge
    def knowledge_stats(self, t):
        return {"records": 1, "records_week": 1, "records_archived": 0, "manual_sections": 12, "documents": 2,
                "history": 56, "questions_30d": 10, "answered_30d": 8}

    def knowledge_records(self, t, *, machine, q, archived, limit):
        out = []
        for r in self.records.values():
            if r["tenant_id"] != t or r["status"] != "approved" or bool(r["archived_at"]) != archived:
                continue
            if q and q.lower() not in str(r["fields"]).lower():
                continue
            out.append(dict(r, machine_code="HP-07", author_name="Ramesh Patil", reviewer_name="Suresh Kulkarni",
                            reviewed_at=now() - timedelta(days=2), created_at=now() - timedelta(days=3),
                            source="capture", language="mr-IN", used=5))
        return out[:limit]

    def knowledge_documents(self, t, *, machine, q, limit):
        if t != TENANT or (q and "manual" not in q.lower()):
            return []
        return [dict(id="ffffffff-0000-0000-0000-000000000001", title="HPX-200 Service Manual", type="manual",
                     status="ready", pages=4, quality_notes="Page 4 is a scanned image.", created_at=now() - timedelta(days=10),
                     model="HPX-200", sections=12, used=9)][:limit]

    def knowledge_logs(self, t, *, machine, q, limit):
        if t != TENANT or q:
            return []
        return [dict(id="ffffffff-0000-0000-0000-000000000002", date=date(2025, 10, 3), fault="pressure low",
                     action="seal kit", downtime_min=150, technician="Vijay", created_at=now() - timedelta(days=30),
                     machine_code="HP-07", used=1)][:limit]

    def get_record(self, t, rid):
        r = self.records.get(rid)
        return copy.deepcopy(r) if r and r["tenant_id"] == t else None

    def archive_record(self, t, rid, actor):
        self.records[rid]["archived_at"] = now()
        self.chunks.discard(rid)
        return 1

    def unarchive_record(self, t, rid):
        self.records[rid]["archived_at"] = None
        return 1

    # analytics + logs
    def analytics(self, t, days):
        d0 = date.today()
        return {"totals": {"questions": 10, "answered": 8, "no_answer": 1, "failed": 1, "voice": 6, "escalated": 2,
                           "first_word_ms": 1840.0},
                "feedback": {"fixed": 5, "not_fixed": 1, "feedback": 6},
                "escalations": {"created": 2, "answered": 1, "minutes_to_answer": 42.5, "open_now": 1},
                "notes": {"sent": 4, "approved": 3, "rejected": 1, "hours_to_review": 5.25, "pending_now": 2},
                "per_day": [{"day": d0 - timedelta(days=i), "questions": i, "answered": i, "escalated": 0}
                            for i in reversed(range(days))],
                "machines": [{"code": "HP-07", "name": "Hydraulic press", "questions": 6, "no_answer": 1, "escalated": 1}],
                "gaps": [{"id": uuid.uuid4(), "question_en": "AC-01 trips when hot", "question_original": None,
                          "status": "no_answer", "created_at": now(), "machine_code": "AC-01",
                          "escalation_status": "open"}],
                "team": [{"id": RAMESH, "name": "Ramesh Patil", "role": "expert", "questions": 0, "notes_sent": 3,
                          "notes_approved": 3, "answers_given": 1, "knowledge_used": 7}]}

    def list_log_imports(self, t, limit):
        return [{"id": uuid.uuid4(), "file_name": "shree_breakdown_log.xlsx", "status": "done", "rows_ok": 56,
                 "rows_skipped": 4, "created_at": now(), "created_by_name": "Suresh Kulkarni"}] if t == TENANT else []

    def list_maintenance_logs(self, t, machine, limit):
        return [{"id": uuid.uuid4(), "date": date(2025, 10, 3), "fault": "pressure low", "action": "seal kit",
                 "downtime_min": 150, "technician": "Vijay", "machine_code": "HP-07",
                 "file_name": "shree_breakdown_log.xlsx"}] if t == TENANT else []
