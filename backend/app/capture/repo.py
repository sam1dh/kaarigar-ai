"""All SQL for Phase 2. Every query filters by tenant_id (the backend bypasses RLS)."""
from __future__ import annotations

from typing import Any, Callable, ContextManager, Protocol

ACTIVE_STAGES = ("queued", "transcribing", "extracting", "checking", "translating")

UPDATABLE = {
    "status", "stage", "error", "language", "audio_seconds", "audio_path", "transcript_en",
    "fields", "fields_local", "ai_check", "safety_note", "symptom_id", "cause_id", "fix_id",
    "reviewed_by", "reviewed_at", "reject_reason", "submitted_at", "edited_by_expert", "edited_by_reviewer",
}
JSON_COLS = {"fields", "fields_local", "ai_check"}
TAXONOMY_TABLES = {"symptom": "symptoms", "cause": "causes", "fix": "fixes"}


class Repo(Protocol):
    def machine_by_code(self, tenant_id: str, code: str) -> dict | None: ...
    def create_record(self, *, record_id: str, tenant_id: str, machine_id: str, author_id: str,
                      language: str, audio_path: str | None, transcript_en: str | None) -> None: ...
    def get(self, tenant_id: str, record_id: str) -> dict | None: ...
    def update(self, tenant_id: str, record_id: str, **cols: Any) -> None: ...
    def delete(self, tenant_id: str, record_id: str) -> None: ...
    def glossary(self, tenant_id: str) -> list[dict]: ...
    def match_taxonomy(self, tenant_id: str, kind: str, text: str) -> dict | None: ...
    def ensure_taxonomy(self, tenant_id: str, kind: str, name: str) -> str: ...
    def add_symptom_alias(self, tenant_id: str, symptom_id: str, alias: str) -> None: ...
    def list_by_author(self, tenant_id: str, author_id: str, machine_id: str | None, limit: int) -> list[dict]: ...
    def review_queue(self, tenant_id: str, limit: int) -> list[dict]: ...
    def pending_count(self, tenant_id: str) -> int: ...
    def mark_stuck_failed(self, error_code: str) -> int: ...


def norm_label(text: str) -> str:
    return " ".join(text.lower().strip().strip(".").split())[:200]


_SELECT_RECORD = """
select r.id, r.tenant_id, r.machine_id, r.author_id, r.audio_path, r.transcript_en, r.symptom_id, r.cause_id,
       r.fix_id, r.safety_note, r.fields, r.ai_check, r.status, r.reject_reason, r.reviewed_by, r.reviewed_at,
       r.source, r.created_at, r.language, r.audio_seconds, r.stage, r.error, r.fields_local, r.submitted_at,
       r.edited_by_expert, r.edited_by_reviewer,
       m.code as machine_code, m.name as machine_name, m.line as machine_line,
       mm.model as machine_model, mm.type as machine_type,
       a.name as author_name, rv.name as reviewer_name
from repair_records r
join machines m on m.id = r.machine_id
left join machine_models mm on mm.id = m.model_id
left join users a on a.id = r.author_id
left join users rv on rv.id = r.reviewed_by
"""


class PostgresRepo:
    """psycopg 3 implementation. `conn_factory` is adapters.db_conn."""

    def __init__(self, conn_factory: Callable[[], ContextManager[Any]]):
        self._conn = conn_factory

    # -- helpers -----------------------------------------------------------
    def _all(self, sql: str, params: dict) -> list[dict]:
        from psycopg.rows import dict_row

        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())

    def _one(self, sql: str, params: dict) -> dict | None:
        rows = self._all(sql, params)
        return rows[0] if rows else None

    def _exec(self, sql: str, params: dict) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                n = cur.rowcount
            conn.commit()
            return n

    # -- machines ----------------------------------------------------------
    def machine_by_code(self, tenant_id: str, code: str) -> dict | None:
        return self._one(
            """select m.id, m.code, m.name, m.line, m.model_id, mm.model, mm.type
               from machines m left join machine_models mm on mm.id = m.model_id
               where m.tenant_id = %(t)s and m.archived_at is null
                 and upper(m.code) = upper(%(c)s)""",
            {"t": tenant_id, "c": code.strip()},
        )

    # -- records -----------------------------------------------------------
    def create_record(self, *, record_id: str, tenant_id: str, machine_id: str, author_id: str,
                      language: str, audio_path: str | None, transcript_en: str | None) -> None:
        from psycopg.types.json import Jsonb

        self._exec(
            """insert into repair_records
                 (id, tenant_id, machine_id, author_id, audio_path, transcript_en, fields, status, source,
                  language, stage)
               values (%(id)s, %(t)s, %(m)s, %(a)s, %(p)s, %(tx)s, %(f)s, 'draft', 'capture', %(lang)s, 'queued')""",
            {"id": record_id, "t": tenant_id, "m": machine_id, "a": author_id, "p": audio_path,
             "tx": transcript_en, "f": Jsonb({}), "lang": language},
        )

    def get(self, tenant_id: str, record_id: str) -> dict | None:
        return self._one(_SELECT_RECORD + " where r.tenant_id = %(t)s and r.id = %(id)s",
                         {"t": tenant_id, "id": record_id})

    def update(self, tenant_id: str, record_id: str, **cols: Any) -> None:
        from psycopg import sql
        from psycopg.types.json import Jsonb

        bad = set(cols) - UPDATABLE
        if bad:
            raise ValueError(f"not updatable: {bad}")
        if not cols:
            return
        params = {"t": tenant_id, "id": record_id}
        sets = []
        for k, v in cols.items():
            params[k] = Jsonb(v) if (k in JSON_COLS and v is not None) else v
            sets.append(sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder(k)))
        q = sql.SQL("update repair_records set {} where tenant_id = %(t)s and id = %(id)s").format(
            sql.SQL(", ").join(sets))
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(q, params)
            conn.commit()

    def delete(self, tenant_id: str, record_id: str) -> None:
        self._exec("delete from chunks where tenant_id = %(t)s and source_type = 'record' and source_id = %(id)s",
                   {"t": tenant_id, "id": record_id})
        self._exec("delete from repair_records where tenant_id = %(t)s and id = %(id)s",
                   {"t": tenant_id, "id": record_id})

    def list_by_author(self, tenant_id: str, author_id: str, machine_id: str | None, limit: int) -> list[dict]:
        return self._all(
            _SELECT_RECORD + """ where r.tenant_id = %(t)s and r.author_id = %(a)s and r.source = 'capture'
                and (%(m)s::uuid is null or r.machine_id = %(m)s)
                order by r.created_at desc limit %(n)s""",
            {"t": tenant_id, "a": author_id, "m": machine_id, "n": limit},
        )

    def review_queue(self, tenant_id: str, limit: int) -> list[dict]:
        return self._all(
            _SELECT_RECORD + """ where r.tenant_id = %(t)s and r.status = 'pending'
                order by r.submitted_at asc nulls last limit %(n)s""",
            {"t": tenant_id, "n": limit},
        )

    def pending_count(self, tenant_id: str) -> int:
        row = self._one("select count(*) as n from repair_records where tenant_id = %(t)s and status = 'pending'",
                        {"t": tenant_id})
        return int(row["n"]) if row else 0

    def mark_stuck_failed(self, error_code: str) -> int:
        """On startup: anything mid-pipeline was interrupted by a restart (all tenants, by design)."""
        return self._exec(
            "update repair_records set stage = 'failed', error = %(e)s where stage = any(%(s)s)",
            {"e": error_code, "s": list(ACTIVE_STAGES)},
        )

    # -- glossary & taxonomy -------------------------------------------------
    def glossary(self, tenant_id: str) -> list[dict]:
        return self._all("select term, meaning from glossary where tenant_id = %(t)s order by term limit 60",
                         {"t": tenant_id})

    def match_taxonomy(self, tenant_id: str, kind: str, text: str) -> dict | None:
        table = TAXONOMY_TABLES[kind]
        from psycopg import sql

        q = sql.SQL("""select id, name,
                   greatest(similarity(name, %(x)s),
                            coalesce((select max(similarity(a, %(x)s)) from unnest(aliases) a), 0)) as sim
                 from {} where tenant_id = %(t)s order by sim desc limit 1""").format(sql.Identifier(table))
        from psycopg.rows import dict_row

        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(q, {"t": tenant_id, "x": norm_label(text)})
                row = cur.fetchone()
        if not row:
            return None
        return {"id": str(row["id"]), "name": row["name"], "sim": float(row["sim"] or 0)}

    def ensure_taxonomy(self, tenant_id: str, kind: str, name: str) -> str:
        from psycopg import sql
        from psycopg.rows import dict_row

        q = sql.SQL("""insert into {} (tenant_id, name) values (%(t)s, %(n)s)
                       on conflict (tenant_id, name) do update set name = excluded.name
                       returning id""").format(sql.Identifier(TAXONOMY_TABLES[kind]))
        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(q, {"t": tenant_id, "n": norm_label(name)})
                rid = cur.fetchone()["id"]
            conn.commit()
        return str(rid)

    def add_symptom_alias(self, tenant_id: str, symptom_id: str, alias: str) -> None:
        self._exec(
            """update symptoms set aliases = array_append(aliases, %(a)s)
               where tenant_id = %(t)s and id = %(id)s and not (%(a)s = any(aliases)) and name <> %(a)s
                 and coalesce(array_length(aliases, 1), 0) < 30""",
            {"t": tenant_id, "id": symptom_id, "a": norm_label(alias)},
        )
