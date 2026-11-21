"""All SQL for Phase 3. Every query filters by tenant_id (the backend bypasses RLS)."""
from __future__ import annotations

from typing import Any, Callable, ContextManager, Protocol

QUERY_UPDATABLE = {
    "status", "question_original", "question_en", "answer", "answer_local", "answer_parts", "sources",
    "citations", "confidence", "latency_ms", "first_token_ms", "model", "error", "audio_seconds", "escalated",
    "audio_path",
}
QUERY_JSON = {"answer_parts", "sources", "citations"}
FINAL_STATUSES = ("answered", "no_answer", "failed", "cancelled")


class AssistRepo(Protocol):
    def machine_by_code(self, tenant_id: str, code: str) -> dict | None: ...
    def machine_by_qr(self, tenant_id: str, token: str) -> dict | None: ...
    def machine_codes(self, tenant_id: str) -> list[str]: ...
    def create_query(self, *, query_id: str, tenant_id: str, user_id: str, machine_id: str | None,
                     language: str, input_mode: str, audio_path: str | None,
                     question_original: str | None) -> None: ...
    def update_query(self, tenant_id: str, query_id: str, **cols: Any) -> None: ...
    def get_query(self, tenant_id: str, query_id: str) -> dict | None: ...
    def list_queries(self, tenant_id: str, user_id: str, limit: int) -> list[dict]: ...
    def mark_stuck_answering(self, error_code: str) -> int: ...
    def upsert_feedback(self, tenant_id: str, query_id: str, user_id: str, outcome: str) -> None: ...
    def pick_expert(self, tenant_id: str, machine_id: str | None, exclude_user: str) -> str | None: ...
    def create_escalation(self, *, tenant_id: str, query_id: str, asked_by: str, machine_id: str | None,
                          note: str | None, assigned_to: str | None) -> str | None: ...
    def get_escalation(self, tenant_id: str, escalation_id: str) -> dict | None: ...
    def escalation_id_for_query(self, tenant_id: str, query_id: str) -> str | None: ...
    def list_escalations(self, tenant_id: str, *, status: str | None, assigned_to: str | None,
                         include_unassigned: bool, limit: int) -> list[dict]: ...
    def escalation_counts(self, tenant_id: str, user_id: str | None = None) -> dict: ...
    def assign_escalation(self, tenant_id: str, escalation_id: str, user_id: str) -> bool: ...
    def close_escalation(self, tenant_id: str, escalation_id: str, reason: str) -> bool: ...
    def close_open_for_query(self, tenant_id: str, query_id: str, reason: str) -> bool: ...
    def set_reply_text(self, tenant_id: str, escalation_id: str, user_id: str, text: str) -> bool: ...
    def set_reply_local(self, tenant_id: str, escalation_id: str, data: dict) -> None: ...
    def link_reply_record(self, tenant_id: str, record_id: str, escalation_id: str) -> None: ...
    def experts(self, tenant_id: str) -> list[dict]: ...
    def user_in_tenant(self, tenant_id: str, user_id: str) -> dict | None: ...
    def record_source(self, tenant_id: str, record_id: str) -> dict | None: ...
    def manual_page(self, tenant_id: str, document_id: str, page: int | None) -> dict | None: ...
    def log_source(self, tenant_id: str, log_id: str) -> dict | None: ...


_SELECT_QUERY = """
select q.id, q.tenant_id, q.user_id, q.machine_id, q.question_original, q.question_en, q.language, q.answer,
       q.answer_local, q.answer_parts, q.sources, q.citations, q.confidence, q.escalated, q.latency_ms,
       q.first_token_ms, q.status, q.input_mode, q.audio_path, q.audio_seconds, q.error, q.model, q.created_at,
       m.code as machine_code, m.name as machine_name, mm.model as machine_model,
       u.name as user_name,
       f.outcome as feedback,
       e.id as escalation_id, e.status as escalation_status, e.assigned_to as escalation_assigned_to,
       ea.name as escalation_assigned_name, e.answered_at as escalation_answered_at
from queries q
left join machines m on m.id = q.machine_id
left join machine_models mm on mm.id = m.model_id
left join users u on u.id = q.user_id
left join feedback f on f.query_id = q.id and f.user_id = q.user_id
left join escalations e on e.query_id = q.id
left join users ea on ea.id = e.assigned_to
"""

_SELECT_ESC = """
select e.id, e.tenant_id, e.query_id, e.status, e.assigned_to, e.assigned_at, e.asked_by, e.machine_id, e.note,
       e.reply_text, e.reply_local, e.replied_by, e.new_record_id, e.created_at, e.answered_at, e.closed_at,
       e.close_reason,
       q.question_original, q.question_en, q.language as question_language, q.answer, q.answer_local,
       q.answer_parts, q.sources, q.status as answer_status, q.confidence, q.created_at as asked_at,
       q.user_id as query_user_id,
       m.code as machine_code, m.name as machine_name, m.line as machine_line, mm.model as machine_model,
       ab.name as asked_by_name, ab.language as asked_by_language,
       asg.name as assigned_name, rp.name as replied_name,
       f.outcome as feedback,
       rr.id as reply_record_id, rr.status as reply_record_status, rr.stage as reply_record_stage,
       rr.fields as reply_fields, rr.fields_local as reply_fields_local, rr.language as reply_language,
       rr.audio_path as reply_audio_path, rr.author_id as reply_author_id, rr.transcript_en as reply_transcript_en
from escalations e
join queries q on q.id = e.query_id
left join machines m on m.id = e.machine_id
left join machine_models mm on mm.id = m.model_id
left join users ab on ab.id = e.asked_by
left join users asg on asg.id = e.assigned_to
left join users rp on rp.id = e.replied_by
left join feedback f on f.query_id = q.id and f.user_id = q.user_id
left join lateral (
    select r.* from repair_records r
    where r.tenant_id = e.tenant_id
      and (r.id = e.new_record_id or (e.new_record_id is null and r.escalation_id = e.id))
    order by (r.id = e.new_record_id) desc, r.created_at desc
    limit 1
) rr on true
"""


class PostgresAssistRepo:
    """psycopg 3 implementation. `conn_factory` is adapters.db_conn."""

    def __init__(self, conn_factory: Callable[[], ContextManager[Any]]):
        self._conn = conn_factory

    # -- helpers -----------------------------------------------------------
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

    def _returning(self, sql: Any, params: dict) -> dict | None:
        from psycopg.rows import dict_row

        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
            conn.commit()
            return row

    # -- machines ----------------------------------------------------------
    _MACHINE = """select m.id, m.code, m.name, m.line, m.model_id, mm.model, mm.type
                  from machines m left join machine_models mm on mm.id = m.model_id
                  where m.tenant_id = %(t)s and m.archived_at is null and """

    def machine_by_code(self, tenant_id: str, code: str) -> dict | None:
        return self._one(self._MACHINE + "upper(m.code) = upper(%(c)s)", {"t": tenant_id, "c": code.strip()})

    def machine_by_qr(self, tenant_id: str, token: str) -> dict | None:
        return self._one(self._MACHINE + "m.qr_token = %(q)s", {"t": tenant_id, "q": token.strip()})

    def machine_codes(self, tenant_id: str) -> list[str]:
        return [r["code"] for r in self._all(
            "select code from machines where tenant_id = %(t)s and archived_at is null order by code limit 500",
            {"t": tenant_id})]

    # -- queries -----------------------------------------------------------
    def create_query(self, *, query_id: str, tenant_id: str, user_id: str, machine_id: str | None,
                     language: str, input_mode: str, audio_path: str | None,
                     question_original: str | None) -> None:
        self._exec(
            """insert into queries (id, tenant_id, user_id, machine_id, language, input_mode, audio_path,
                                    question_original, status)
               values (%(id)s, %(t)s, %(u)s, %(m)s, %(l)s, %(mode)s, %(p)s, %(qo)s, 'answering')""",
            {"id": query_id, "t": tenant_id, "u": user_id, "m": machine_id, "l": language, "mode": input_mode,
             "p": audio_path, "qo": question_original},
        )

    def update_query(self, tenant_id: str, query_id: str, **cols: Any) -> None:
        from psycopg import sql
        from psycopg.types.json import Jsonb

        bad = set(cols) - QUERY_UPDATABLE
        if bad:
            raise ValueError(f"not updatable: {bad}")
        if not cols:
            return
        params: dict = {"t": tenant_id, "id": query_id}
        sets = []
        for k, v in cols.items():
            params[k] = Jsonb(v) if (k in QUERY_JSON and v is not None) else v
            sets.append(sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder(k)))
        q = sql.SQL("update queries set {} where tenant_id = %(t)s and id = %(id)s").format(sql.SQL(", ").join(sets))
        self._exec(q, params)

    def get_query(self, tenant_id: str, query_id: str) -> dict | None:
        return self._one(_SELECT_QUERY + " where q.tenant_id = %(t)s and q.id = %(id)s",
                         {"t": tenant_id, "id": query_id})

    def list_queries(self, tenant_id: str, user_id: str, limit: int) -> list[dict]:
        return self._all(_SELECT_QUERY + """ where q.tenant_id = %(t)s and q.user_id = %(u)s
                                              and q.status <> 'cancelled'
                                              order by q.created_at desc limit %(n)s""",
                         {"t": tenant_id, "u": user_id, "n": limit})

    def mark_stuck_answering(self, error_code: str) -> int:
        """On startup: a question still 'answering' was cut off by a restart (all plants, by design)."""
        return self._exec("update queries set status = 'failed', error = %(e)s where status = 'answering'",
                          {"e": error_code})

    # -- feedback ------------------------------------------------------------
    def upsert_feedback(self, tenant_id: str, query_id: str, user_id: str, outcome: str) -> None:
        self._exec(
            """insert into feedback (tenant_id, query_id, user_id, outcome) values (%(t)s, %(q)s, %(u)s, %(o)s)
               on conflict (query_id, user_id) do update set outcome = excluded.outcome, created_at = now()""",
            {"t": tenant_id, "q": query_id, "u": user_id, "o": outcome},
        )

    # -- escalations -----------------------------------------------------------
    def pick_expert(self, tenant_id: str, machine_id: str | None, exclude_user: str) -> str | None:
        """The expert who has fixed this machine most, then this model, then the least busy one."""
        row = self._one(
            """select u.id from users u
               where u.tenant_id = %(t)s and u.role = 'expert' and u.id <> %(x)s
               order by
                 (select count(*) from repair_records r
                   where r.tenant_id = u.tenant_id and r.author_id = u.id and r.status = 'approved'
                     and r.machine_id = %(m)s) desc,
                 (select count(*) from repair_records r join machines rm on rm.id = r.machine_id
                   where r.tenant_id = u.tenant_id and r.author_id = u.id and r.status = 'approved'
                     and rm.model_id = (select model_id from machines where id = %(m)s)) desc,
                 (select count(*) from escalations e
                   where e.tenant_id = u.tenant_id and e.assigned_to = u.id and e.status = 'open') asc,
                 u.name
               limit 1""",
            {"t": tenant_id, "m": machine_id, "x": exclude_user},
        )
        return str(row["id"]) if row else None

    def create_escalation(self, *, tenant_id: str, query_id: str, asked_by: str, machine_id: str | None,
                          note: str | None, assigned_to: str | None) -> str | None:
        """Returns the new id, or None if this question was already escalated."""
        from psycopg.rows import dict_row

        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """insert into escalations (tenant_id, query_id, asked_by, machine_id, note, assigned_to,
                                                assigned_at, status)
                       values (%(t)s, %(q)s, %(a)s, %(m)s, %(n)s, %(as)s,
                               case when %(as)s::uuid is null then null else now() end, 'open')
                       on conflict (query_id) do nothing
                       returning id""",
                    {"t": tenant_id, "q": query_id, "a": asked_by, "m": machine_id, "n": note, "as": assigned_to},
                )
                row = cur.fetchone()
                if row:
                    cur.execute("update queries set escalated = true where tenant_id = %(t)s and id = %(q)s",
                                {"t": tenant_id, "q": query_id})
            conn.commit()
        return str(row["id"]) if row else None

    def get_escalation(self, tenant_id: str, escalation_id: str) -> dict | None:
        return self._one(_SELECT_ESC + " where e.tenant_id = %(t)s and e.id = %(id)s",
                         {"t": tenant_id, "id": escalation_id})

    def escalation_id_for_query(self, tenant_id: str, query_id: str) -> str | None:
        row = self._one("select id from escalations where tenant_id = %(t)s and query_id = %(q)s",
                        {"t": tenant_id, "q": query_id})
        return str(row["id"]) if row else None

    def list_escalations(self, tenant_id: str, *, status: str | None, assigned_to: str | None,
                         include_unassigned: bool, limit: int) -> list[dict]:
        where = ["e.tenant_id = %(t)s"]
        params: dict = {"t": tenant_id, "n": limit}
        if status:
            where.append("e.status = %(s)s")
            params["s"] = status
        if assigned_to:
            params["a"] = assigned_to
            where.append("(e.assigned_to = %(a)s or e.assigned_to is null)" if include_unassigned
                         else "e.assigned_to = %(a)s")
        order = ("case e.status when 'open' then 0 when 'answered' then 1 else 2 end, "
                 "case when e.status = 'open' then e.created_at end asc, "
                 "coalesce(e.answered_at, e.closed_at, e.created_at) desc")
        return self._all(_SELECT_ESC + " where " + " and ".join(where) + f" order by {order} limit %(n)s", params)

    def escalation_counts(self, tenant_id: str, user_id: str | None = None) -> dict:
        row = self._one(
            """select count(*) filter (where status = 'open') as open,
                      count(*) filter (where status = 'open' and assigned_to is null) as unassigned,
                      count(*) filter (where status = 'open' and assigned_to = %(u)s) as mine
               from escalations where tenant_id = %(t)s""",
            {"t": tenant_id, "u": user_id},
        ) or {}
        return {"open": int(row.get("open") or 0), "unassigned": int(row.get("unassigned") or 0),
                "mine": int(row.get("mine") or 0)}

    def assign_escalation(self, tenant_id: str, escalation_id: str, user_id: str) -> bool:
        return self._exec(
            """update escalations set assigned_to = %(u)s, assigned_at = now()
               where tenant_id = %(t)s and id = %(id)s and status = 'open'""",
            {"t": tenant_id, "id": escalation_id, "u": user_id},
        ) == 1

    def close_escalation(self, tenant_id: str, escalation_id: str, reason: str) -> bool:
        return self._exec(
            """update escalations set status = 'closed', closed_at = now(), close_reason = %(r)s
               where tenant_id = %(t)s and id = %(id)s and status <> 'closed'""",
            {"t": tenant_id, "id": escalation_id, "r": reason},
        ) == 1

    def close_open_for_query(self, tenant_id: str, query_id: str, reason: str) -> bool:
        return self._exec(
            """update escalations set status = 'closed', closed_at = now(), close_reason = %(r)s
               where tenant_id = %(t)s and query_id = %(q)s and status = 'open'""",
            {"t": tenant_id, "q": query_id, "r": reason},
        ) == 1

    def set_reply_text(self, tenant_id: str, escalation_id: str, user_id: str, text: str) -> bool:
        return self._exec(
            """update escalations
                  set reply_text = %(x)s, replied_by = %(u)s, status = 'answered', answered_at = now(),
                      reply_local = null, assigned_to = coalesce(assigned_to, %(u)s),
                      assigned_at = coalesce(assigned_at, now())
               where tenant_id = %(t)s and id = %(id)s and status = 'open'""",
            {"t": tenant_id, "id": escalation_id, "u": user_id, "x": text},
        ) == 1

    def set_reply_local(self, tenant_id: str, escalation_id: str, data: dict) -> None:
        from psycopg.types.json import Jsonb

        self._exec("update escalations set reply_local = %(d)s where tenant_id = %(t)s and id = %(id)s",
                   {"t": tenant_id, "id": escalation_id, "d": Jsonb(data)})

    def link_reply_record(self, tenant_id: str, record_id: str, escalation_id: str) -> None:
        self._exec(
            """update repair_records set source = 'escalation', escalation_id = %(e)s
               where tenant_id = %(t)s and id = %(r)s""",
            {"t": tenant_id, "r": record_id, "e": escalation_id},
        )

    # -- people ----------------------------------------------------------------
    def experts(self, tenant_id: str) -> list[dict]:
        return self._all(
            """select u.id, u.name, u.role, u.language,
                      (select count(*) from escalations e where e.tenant_id = u.tenant_id
                         and e.assigned_to = u.id and e.status = 'open') as open_assigned,
                      (select count(*) from repair_records r where r.tenant_id = u.tenant_id
                         and r.author_id = u.id and r.status = 'approved') as approved_records
               from users u
               where u.tenant_id = %(t)s and u.role in ('expert', 'supervisor')
               order by case u.role when 'expert' then 0 else 1 end, u.name""",
            {"t": tenant_id},
        )

    def user_in_tenant(self, tenant_id: str, user_id: str) -> dict | None:
        return self._one("select id, name, role, language from users where tenant_id = %(t)s and id = %(u)s",
                         {"t": tenant_id, "u": user_id})

    # -- sources ---------------------------------------------------------------
    def record_source(self, tenant_id: str, record_id: str) -> dict | None:
        return self._one(
            """select r.id, r.status, r.author_id, r.fields, r.fields_local, r.language, r.safety_note,
                      r.audio_path, r.audio_seconds, r.created_at, r.reviewed_at, r.source,
                      m.code as machine_code, m.name as machine_name, mm.model as machine_model,
                      a.name as author_name, rv.name as reviewer_name
               from repair_records r
               join machines m on m.id = r.machine_id
               left join machine_models mm on mm.id = m.model_id
               left join users a on a.id = r.author_id
               left join users rv on rv.id = r.reviewed_by
               where r.tenant_id = %(t)s and r.id = %(id)s""",
            {"t": tenant_id, "id": record_id},
        )

    def manual_page(self, tenant_id: str, document_id: str, page: int | None) -> dict | None:
        doc = self._one(
            """select d.id, d.title, d.type, d.file_path, d.pages, d.status, mm.model as model
               from documents d left join machine_models mm on mm.id = d.model_id
               where d.tenant_id = %(t)s and d.id = %(id)s""",
            {"t": tenant_id, "id": document_id},
        )
        if not doc:
            return None
        chunks = self._all(
            """select section, text, page, chunk_index from chunks
               where tenant_id = %(t)s and source_type = 'manual' and source_id = %(id)s
                 and (%(p)s::int is null or page = %(p)s)
               order by page nulls last, chunk_index limit 12""",
            {"t": tenant_id, "id": document_id, "p": page},
        )
        doc["chunks"] = chunks
        return doc

    def log_source(self, tenant_id: str, log_id: str) -> dict | None:
        return self._one(
            """select l.id, l.date, l.fault, l.action, l.downtime_min, l.technician,
                      m.code as machine_code, m.name as machine_name
               from maintenance_logs l left join machines m on m.id = l.machine_id
               where l.tenant_id = %(t)s and l.id = %(id)s""",
            {"t": tenant_id, "id": log_id},
        )
