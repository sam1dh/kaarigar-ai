"""All SQL for Phase 4. Every query filters by tenant_id (the backend bypasses RLS)."""
from __future__ import annotations

import logging
from typing import Any, Callable, ContextManager

log = logging.getLogger("kaarigar.manage.repo")

PERSON_UPDATABLE = {"name", "role", "language", "is_admin"}
MACHINE_UPDATABLE = {"code", "name", "line", "model_id"}

# How often a source was cited in an answer (Phase 3 stores citations as [{ref, source_type, source_id, seed_key}])
_USED = """(select count(*) from queries q
             where q.tenant_id = %(t)s and q.status = 'answered'
               and q.citations @> jsonb_build_array(jsonb_build_object('source_id', {col}::text)))"""


class PostgresManageRepo:
    def __init__(self, conn_factory: Callable[[], ContextManager[Any]]):
        self._conn = conn_factory

    # ------------------------------------------------------------------ helpers
    def _all(self, sql: Any, params: dict) -> list[dict]:
        from psycopg.rows import dict_row

        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())

    def _one(self, sql: Any, params: dict) -> dict | None:
        rows = self._all(sql, params)
        return rows[0] if rows else None

    def _exec(self, sql: Any, params: dict) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                n = cur.rowcount
            conn.commit()
            return n

    def _update(self, table: str, allowed: set[str], tenant_id: str, row_id: str, cols: dict) -> int:
        from psycopg import sql

        bad = set(cols) - allowed
        if bad:
            raise ValueError(f"not updatable: {bad}")
        if not cols:
            return 0
        params = {"t": tenant_id, "id": row_id, **cols}
        sets = sql.SQL(", ").join(sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder(k)) for k in cols)
        q = sql.SQL("update {} set {} where tenant_id = %(t)s and id = %(id)s").format(sql.Identifier(table), sets)
        return self._exec(q, params)

    # ------------------------------------------------------------------ tenant + audit
    def tenant(self, tenant_id: str) -> dict | None:
        return self._one("select id, name, slug from tenants where id = %(t)s", {"t": tenant_id})

    def audit(self, tenant_id: str, actor_id: str | None, action: str, target_type: str, target_id: str | None,
              detail: dict | None = None) -> None:
        from psycopg.types.json import Jsonb

        self._exec(
            """insert into admin_audit (tenant_id, actor_id, action, target_type, target_id, detail)
               values (%(t)s, %(a)s, %(act)s, %(tt)s, %(tid)s, %(d)s)""",
            {"t": tenant_id, "a": actor_id, "act": action, "tt": target_type, "tid": target_id,
             "d": Jsonb(detail or {})},
        )

    def audit_list(self, tenant_id: str, limit: int) -> list[dict]:
        return self._all(
            """select a.id, a.action, a.target_type, a.target_id, a.detail, a.created_at, u.name as actor_name
               from admin_audit a left join users u on u.id = a.actor_id
               where a.tenant_id = %(t)s order by a.created_at desc limit %(n)s""",
            {"t": tenant_id, "n": limit},
        )

    # ------------------------------------------------------------------ people
    _PEOPLE_COLS = """u.id, u.name, u.employee_id, u.role, u.is_admin, u.language, u.created_at, u.deactivated_at,
        (select max(q.created_at) from queries q where q.tenant_id = u.tenant_id and q.user_id = u.id) as last_question_at,
        (select max(r.created_at) from repair_records r where r.tenant_id = u.tenant_id and r.author_id = u.id) as last_note_at,
        (select count(*) from repair_records r where r.tenant_id = u.tenant_id and r.author_id = u.id
           and r.status = 'approved') as approved_notes"""

    def _people(self, tenant_id: str, where: str, params: dict) -> list[dict]:
        base = {"t": tenant_id, **params}
        try:
            return self._all(
                f"""select {self._PEOPLE_COLS}, au.email, au.last_sign_in_at
                    from users u left join auth.users au on au.id = u.id
                    where u.tenant_id = %(t)s {where}
                    order by u.deactivated_at nulls first,
                             case u.role when 'supervisor' then 0 when 'expert' then 1 else 2 end, u.name""",
                base,
            )
        except Exception as e:  # noqa: BLE001  some setups can't read auth.users: show the list without sign-in times
            log.info("auth.users not readable (%s); people listed without last sign-in", type(e).__name__)
            return self._all(
                f"""select {self._PEOPLE_COLS}, null::text as email, null::timestamptz as last_sign_in_at
                    from users u where u.tenant_id = %(t)s {where}
                    order by u.deactivated_at nulls first,
                             case u.role when 'supervisor' then 0 when 'expert' then 1 else 2 end, u.name""",
                base,
            )

    def list_people(self, tenant_id: str) -> list[dict]:
        return self._people(tenant_id, "", {})

    def get_person(self, tenant_id: str, user_id: str) -> dict | None:
        rows = self._people(tenant_id, "and u.id = %(id)s", {"id": user_id})
        return rows[0] if rows else None

    def employee_id_taken(self, tenant_id: str, employee_id: str) -> bool:
        return self._one("select 1 as x from users where tenant_id = %(t)s and upper(employee_id) = upper(%(e)s)",
                         {"t": tenant_id, "e": employee_id}) is not None

    def insert_person(self, *, user_id: str, tenant_id: str, name: str, employee_id: str | None, role: str,
                      is_admin: bool, language: str, created_by: str | None) -> None:
        self._exec(
            """insert into users (id, tenant_id, name, employee_id, role, is_admin, language, created_by)
               values (%(id)s, %(t)s, %(n)s, %(e)s, %(r)s, %(a)s, %(l)s, %(c)s)""",
            {"id": user_id, "t": tenant_id, "n": name, "e": employee_id, "r": role, "a": is_admin, "l": language,
             "c": created_by},
        )

    def update_person(self, tenant_id: str, user_id: str, **cols: Any) -> int:
        return self._update("users", PERSON_UPDATABLE, tenant_id, user_id, cols)

    def set_deactivated(self, tenant_id: str, user_id: str, deactivated: bool) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""update users set deactivated_at = {'now()' if deactivated else 'null'}
                        where tenant_id = %(t)s and id = %(id)s""",
                    {"t": tenant_id, "id": user_id},
                )
                n = cur.rowcount
                if deactivated and n:
                    # their open questions go back to "not assigned" so the supervisor can pick someone else
                    cur.execute("""update escalations set assigned_to = null, assigned_at = null
                                   where tenant_id = %(t)s and assigned_to = %(id)s and status = 'open'""",
                                {"t": tenant_id, "id": user_id})
            conn.commit()
        return n

    def active_admin_count(self, tenant_id: str) -> int:
        row = self._one("""select count(*) as n from users where tenant_id = %(t)s and is_admin
                           and role = 'supervisor' and deactivated_at is null""", {"t": tenant_id})
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------ machines + models
    _MACHINE_COLS = """m.id, m.code, m.name, m.line, m.qr_token, m.created_at, m.archived_at, m.sticker_printed_at,
        m.model_id, mm.model, mm.type, mm.oem,
        (select count(*) from repair_records r where r.tenant_id = m.tenant_id and r.machine_id = m.id
           and r.status = 'approved' and r.archived_at is null) as approved_records,
        (select count(*) from queries q where q.tenant_id = m.tenant_id and q.machine_id = m.id
           and q.created_at > now() - interval '30 days') as questions_30d,
        lb.date as last_breakdown_date, lb.fault as last_breakdown_fault"""

    def list_machines(self, tenant_id: str, include_archived: bool) -> list[dict]:
        return self._all(
            f"""select {self._MACHINE_COLS}
                from machines m
                left join machine_models mm on mm.id = m.model_id
                left join lateral (select l.date, l.fault from maintenance_logs l
                                   where l.tenant_id = m.tenant_id and l.machine_id = m.id
                                   order by l.date desc nulls last, l.created_at desc limit 1) lb on true
                where m.tenant_id = %(t)s {'' if include_archived else 'and m.archived_at is null'}
                order by m.archived_at nulls first, m.code""",
            {"t": tenant_id},
        )

    def get_machine(self, tenant_id: str, machine_id: str) -> dict | None:
        return self._one(
            f"""select {self._MACHINE_COLS}
                from machines m
                left join machine_models mm on mm.id = m.model_id
                left join lateral (select l.date, l.fault from maintenance_logs l
                                   where l.tenant_id = m.tenant_id and l.machine_id = m.id
                                   order by l.date desc nulls last, l.created_at desc limit 1) lb on true
                where m.tenant_id = %(t)s and m.id = %(id)s""",
            {"t": tenant_id, "id": machine_id},
        )

    def machine_codes(self, tenant_id: str) -> list[dict]:
        return self._all("select id, code from machines where tenant_id = %(t)s", {"t": tenant_id})

    def model_in_tenant(self, tenant_id: str, model_id: str) -> dict | None:
        return self._one("select id, model, type, oem from machine_models where tenant_id = %(t)s and id = %(id)s",
                         {"t": tenant_id, "id": model_id})

    def find_model(self, tenant_id: str, model: str) -> dict | None:
        return self._one("""select id, model, type, oem from machine_models
                            where tenant_id = %(t)s and upper(model) = upper(%(m)s)""", {"t": tenant_id, "m": model})

    def insert_model(self, tenant_id: str, model: str, type_: str | None, oem: str | None) -> dict:
        with self._conn() as conn:
            from psycopg.rows import dict_row

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("""insert into machine_models (tenant_id, model, type, oem) values (%(t)s, %(m)s, %(ty)s, %(o)s)
                               returning id, model, type, oem""", {"t": tenant_id, "m": model, "ty": type_, "o": oem})
                row = cur.fetchone()
            conn.commit()
        return row

    def insert_machine(self, tenant_id: str, code: str, name: str | None, line: str | None, model_id: str | None) -> str:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""insert into machines (tenant_id, code, name, line, model_id)
                               values (%(t)s, %(c)s, %(n)s, %(l)s, %(m)s) returning id""",
                            {"t": tenant_id, "c": code, "n": name, "l": line, "m": model_id})
                mid = cur.fetchone()[0]
            conn.commit()
        return str(mid)

    def update_machine(self, tenant_id: str, machine_id: str, **cols: Any) -> int:
        return self._update("machines", MACHINE_UPDATABLE, tenant_id, machine_id, cols)

    def set_machine_archived(self, tenant_id: str, machine_id: str, archived: bool) -> int:
        return self._exec(f"""update machines set archived_at = {'now()' if archived else 'null'}
                              where tenant_id = %(t)s and id = %(id)s""", {"t": tenant_id, "id": machine_id})

    def renew_qr(self, tenant_id: str, machine_id: str) -> str | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""update machines set qr_token = encode(gen_random_bytes(12), 'hex'), sticker_printed_at = null
                               where tenant_id = %(t)s and id = %(id)s returning qr_token""",
                            {"t": tenant_id, "id": machine_id})
                row = cur.fetchone()
            conn.commit()
        return row[0] if row else None

    def machines_by_ids(self, tenant_id: str, ids: list[str]) -> list[dict]:
        return self._all(
            """select m.id, m.code, m.name, m.line, m.qr_token, mm.model, mm.type
               from machines m left join machine_models mm on mm.id = m.model_id
               where m.tenant_id = %(t)s and m.id = any(%(ids)s::uuid[]) order by m.code""",
            {"t": tenant_id, "ids": ids},
        )

    def mark_printed(self, tenant_id: str, ids: list[str]) -> int:
        return self._exec("""update machines set sticker_printed_at = now()
                             where tenant_id = %(t)s and id = any(%(ids)s::uuid[])""", {"t": tenant_id, "ids": ids})

    # ------------------------------------------------------------------ knowledge base (W6)
    def knowledge_stats(self, tenant_id: str) -> dict:
        row = self._one(
            """select
                 (select count(*) from repair_records where tenant_id = %(t)s and status = 'approved' and archived_at is null) as records,
                 (select count(*) from repair_records where tenant_id = %(t)s and status = 'approved' and archived_at is null
                    and reviewed_at > now() - interval '7 days') as records_week,
                 (select count(*) from repair_records where tenant_id = %(t)s and archived_at is not null) as records_archived,
                 (select count(*) from chunks where tenant_id = %(t)s and source_type = 'manual') as manual_sections,
                 (select count(*) from documents where tenant_id = %(t)s and status = 'ready') as documents,
                 (select count(*) from maintenance_logs where tenant_id = %(t)s) as history,
                 (select count(*) from queries where tenant_id = %(t)s and status <> 'cancelled'
                    and created_at > now() - interval '30 days') as questions_30d,
                 (select count(*) from queries where tenant_id = %(t)s and status = 'answered'
                    and created_at > now() - interval '30 days') as answered_30d""",
            {"t": tenant_id},
        ) or {}
        return {k: int(v or 0) for k, v in row.items()}

    def knowledge_records(self, tenant_id: str, *, machine: str | None, q: str | None, archived: bool,
                          limit: int) -> list[dict]:
        return self._all(
            f"""select r.id, r.fields, r.status, r.archived_at, r.reviewed_at, r.created_at, r.source, r.language,
                       m.code as machine_code, a.name as author_name, rv.name as reviewer_name,
                       {_USED.format(col='r.id')} as used
                from repair_records r
                join machines m on m.id = r.machine_id
                left join users a on a.id = r.author_id
                left join users rv on rv.id = r.reviewed_by
                where r.tenant_id = %(t)s and r.status = 'approved'
                  and (r.archived_at is {'not null' if archived else 'null'})
                  and (%(mc)s::text is null or upper(m.code) = upper(%(mc)s))
                  and (%(q)s::text is null or r.fields::text ilike %(ql)s or r.transcript_en ilike %(ql)s)
                order by r.reviewed_at desc nulls last limit %(n)s""",
            {"t": tenant_id, "mc": machine, "q": q, "ql": f"%{q}%" if q else None, "n": limit},
        )

    def knowledge_documents(self, tenant_id: str, *, machine: str | None, q: str | None, limit: int) -> list[dict]:
        return self._all(
            f"""select d.id, d.title, d.type, d.status, d.pages, d.quality_notes, d.created_at, mm.model,
                       (select count(*) from chunks c where c.tenant_id = d.tenant_id and c.source_type = 'manual'
                          and c.source_id = d.id) as sections,
                       {_USED.format(col='d.id')} as used
                from documents d left join machine_models mm on mm.id = d.model_id
                where d.tenant_id = %(t)s
                  and (%(mc)s::text is null or d.model_id = (select model_id from machines
                                                             where tenant_id = %(t)s and upper(code) = upper(%(mc)s)))
                  and (%(q)s::text is null or d.title ilike %(ql)s or exists (
                        select 1 from chunks c where c.tenant_id = d.tenant_id and c.source_type = 'manual'
                          and c.source_id = d.id and c.text ilike %(ql)s))
                order by d.created_at desc limit %(n)s""",
            {"t": tenant_id, "mc": machine, "q": q, "ql": f"%{q}%" if q else None, "n": limit},
        )

    def knowledge_logs(self, tenant_id: str, *, machine: str | None, q: str | None, limit: int) -> list[dict]:
        return self._all(
            f"""select l.id, l.date, l.fault, l.action, l.downtime_min, l.technician, l.created_at,
                       m.code as machine_code, {_USED.format(col='l.id')} as used
                from maintenance_logs l left join machines m on m.id = l.machine_id
                where l.tenant_id = %(t)s
                  and (%(mc)s::text is null or upper(m.code) = upper(%(mc)s))
                  and (%(q)s::text is null or l.fault ilike %(ql)s or l.action ilike %(ql)s)
                order by l.date desc nulls last, l.created_at desc limit %(n)s""",
            {"t": tenant_id, "mc": machine, "q": q, "ql": f"%{q}%" if q else None, "n": limit},
        )

    def get_record(self, tenant_id: str, record_id: str) -> dict | None:
        return self._one("""select id, status, archived_at, machine_id from repair_records
                            where tenant_id = %(t)s and id = %(id)s""", {"t": tenant_id, "id": record_id})

    def archive_record(self, tenant_id: str, record_id: str, actor_id: str) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""update repair_records set archived_at = now(), archived_by = %(a)s
                               where tenant_id = %(t)s and id = %(id)s and status = 'approved' and archived_at is null""",
                            {"t": tenant_id, "id": record_id, "a": actor_id})
                n = cur.rowcount
                if n:   # out of search right away
                    cur.execute("""delete from chunks where tenant_id = %(t)s and source_type = 'record'
                                   and source_id = %(id)s""", {"t": tenant_id, "id": record_id})
            conn.commit()
        return n

    def unarchive_record(self, tenant_id: str, record_id: str) -> int:
        return self._exec("""update repair_records set archived_at = null, archived_by = null
                             where tenant_id = %(t)s and id = %(id)s and archived_at is not null""",
                          {"t": tenant_id, "id": record_id})

    # ------------------------------------------------------------------ analytics (W3)
    def analytics(self, tenant_id: str, days: int) -> dict:
        p = {"t": tenant_id, "d": days}
        since = "now() - make_interval(days => %(d)s)"
        totals = self._one(
            f"""select
                 count(*) filter (where status <> 'cancelled') as questions,
                 count(*) filter (where status = 'answered') as answered,
                 count(*) filter (where status = 'no_answer') as no_answer,
                 count(*) filter (where status = 'failed') as failed,
                 count(*) filter (where input_mode = 'voice' and status <> 'cancelled') as voice,
                 count(*) filter (where escalated) as escalated,
                 percentile_cont(0.5) within group (order by first_token_ms) filter (where first_token_ms is not null) as first_word_ms
               from queries where tenant_id = %(t)s and created_at > {since}""", p) or {}
        fb = self._one(
            f"""select count(*) filter (where outcome = 'fixed') as fixed,
                       count(*) filter (where outcome = 'not_fixed') as not_fixed,
                       count(*) as feedback
                from feedback where tenant_id = %(t)s and created_at > {since}""", p) or {}
        esc = self._one(
            f"""select count(*) as created,
                       count(*) filter (where status = 'answered') as answered,
                       percentile_cont(0.5) within group (order by extract(epoch from answered_at - created_at) / 60)
                         filter (where answered_at is not null) as minutes_to_answer
                from escalations where tenant_id = %(t)s and created_at > {since}""", p) or {}
        open_now = self._one("select count(*) as n from escalations where tenant_id = %(t)s and status = 'open'", p) or {}
        notes = self._one(
            f"""select count(*) filter (where submitted_at > {since}) as sent,
                       count(*) filter (where status = 'approved' and reviewed_at > {since}) as approved,
                       count(*) filter (where status = 'rejected' and reviewed_at > {since}) as rejected,
                       percentile_cont(0.5) within group (order by extract(epoch from reviewed_at - submitted_at) / 3600)
                         filter (where reviewed_at > {since} and submitted_at is not null) as hours_to_review
                from repair_records where tenant_id = %(t)s""", p) or {}
        pending = self._one("select count(*) as n from repair_records where tenant_id = %(t)s and status = 'pending'", p) or {}
        per_day = self._all(
            f"""select d::date as day,
                       count(q.id) filter (where q.status <> 'cancelled') as questions,
                       count(q.id) filter (where q.status = 'answered') as answered,
                       count(q.id) filter (where q.escalated) as escalated
                from generate_series((now() - make_interval(days => %(d)s - 1))::date, now()::date, interval '1 day') d
                left join queries q on q.tenant_id = %(t)s and q.created_at::date = d::date
                group by d order by d""", p)
        machines = self._all(
            f"""select m.code, m.name,
                       count(q.id) filter (where q.status <> 'cancelled') as questions,
                       count(q.id) filter (where q.status = 'no_answer') as no_answer,
                       count(q.id) filter (where q.escalated) as escalated
                from queries q join machines m on m.id = q.machine_id
                where q.tenant_id = %(t)s and q.created_at > {since}
                group by m.code, m.name
                order by questions desc, m.code limit 6""", p)
        gaps = self._all(
            f"""select q.id, q.question_en, q.question_original, q.status, q.created_at, m.code as machine_code,
                       e.status as escalation_status
                from queries q left join machines m on m.id = q.machine_id
                left join escalations e on e.query_id = q.id
                where q.tenant_id = %(t)s and q.created_at > {since}
                  and (q.status in ('no_answer', 'failed') or q.escalated)
                order by q.created_at desc limit 8""", p)
        team = self._all(
            f"""select u.id, u.name, u.role,
                  (select count(*) from queries q where q.tenant_id = u.tenant_id and q.user_id = u.id
                     and q.status <> 'cancelled' and q.created_at > {since}) as questions,
                  (select count(*) from repair_records r where r.tenant_id = u.tenant_id and r.author_id = u.id
                     and r.submitted_at > {since}) as notes_sent,
                  (select count(*) from repair_records r where r.tenant_id = u.tenant_id and r.author_id = u.id
                     and r.status = 'approved' and r.reviewed_at > {since}) as notes_approved,
                  (select count(*) from escalations e where e.tenant_id = u.tenant_id and e.replied_by = u.id
                     and e.answered_at > {since}) as answers_given,
                  (select count(*) from queries q
                     join lateral jsonb_array_elements(coalesce(q.citations, '[]'::jsonb)) c on true
                     join repair_records r on r.id::text = c->>'source_id' and r.author_id = u.id
                     where q.tenant_id = u.tenant_id and q.status = 'answered' and q.created_at > {since}) as knowledge_used
                from users u
                where u.tenant_id = %(t)s and u.deactivated_at is null
                order by knowledge_used desc, notes_approved desc, answers_given desc, u.name""", p)
        return {"totals": totals, "feedback": fb, "escalations": {**esc, "open_now": open_now.get("n", 0)},
                "notes": {**notes, "pending_now": pending.get("n", 0)}, "per_day": per_day, "machines": machines,
                "gaps": gaps, "team": team}

    # ------------------------------------------------------------------ breakdown logs (W5)
    def list_log_imports(self, tenant_id: str, limit: int) -> list[dict]:
        return self._all(
            """select li.id, li.file_name, li.status, li.rows_ok, li.rows_skipped, li.created_at, u.name as created_by_name
               from log_imports li left join users u on u.id = li.created_by
               where li.tenant_id = %(t)s order by li.created_at desc limit %(n)s""",
            {"t": tenant_id, "n": limit},
        )

    def list_maintenance_logs(self, tenant_id: str, machine: str | None, limit: int) -> list[dict]:
        return self._all(
            """select l.id, l.date, l.fault, l.action, l.downtime_min, l.technician, m.code as machine_code,
                      li.file_name
               from maintenance_logs l left join machines m on m.id = l.machine_id
               left join log_imports li on li.id = l.import_id
               where l.tenant_id = %(t)s and (%(mc)s::text is null or upper(m.code) = upper(%(mc)s))
               order by l.date desc nulls last, l.created_at desc limit %(n)s""",
            {"t": tenant_id, "mc": machine, "n": limit},
        )
