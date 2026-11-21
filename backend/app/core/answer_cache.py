"""Postgres answer cache (Phase 6).

Key: tenant + machine/model + normalised question + ordered top chunk ids.
A hit avoids the LLM entirely; only answers that were grounded in at least one
valid citation are stored. Rows expire after 7 days and are deleted whenever a
repair record for the tenant is approved, rejected or removed.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, ContextManager

_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_question(text: str) -> str:
    return " ".join(_WORD.sub(" ", (text or "").lower()).split())


def question_key(text: str) -> str:
    return hashlib.sha256(normalize_question(text).encode("utf-8")).hexdigest()


def machine_key(machine: dict | None) -> str:
    if not machine:
        return "any"
    parts = [str(machine.get("code") or "").strip().upper(), str(machine.get("model") or "").strip().upper()]
    return "|".join(p for p in parts if p) or "any"


def chunk_key(sources: list[dict]) -> str:
    ids = [str(s.get("chunk_id") or f"{s.get('source_type')}:{s.get('source_id')}:{s.get('page')}")
           for s in sources]
    return hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()


class AnswerCache:
    def __init__(self, conn_factory: Callable[[], ContextManager[Any]], ttl_days: int = 7):
        self._conn = conn_factory
        self.ttl_days = max(1, int(ttl_days))

    def get(self, tenant_id: str, machine: str, q_key: str, c_key: str) -> dict | None:
        from psycopg.rows import dict_row

        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """select answer_local, sources, citations, confidence, model, provider
                       from answer_cache
                       where tenant_id = %(t)s and machine_key = %(m)s and question_key = %(q)s
                         and chunk_key = %(c)s and expires_at > now()""",
                    {"t": tenant_id, "m": machine, "q": q_key, "c": c_key},
                )
                return cur.fetchone()

    def put(self, *, tenant_id: str, machine: str, q_key: str, c_key: str, answer_local: str,
            sources: list[dict], citations: list[dict], confidence: float | None,
            model: str | None, provider: str | None) -> None:
        from psycopg.types.json import Jsonb

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """insert into answer_cache
                         (tenant_id, machine_key, question_key, chunk_key, answer_local, sources,
                          citations, confidence, model, provider, expires_at)
                       values (%(t)s, %(m)s, %(q)s, %(c)s, %(a)s, %(s)s, %(ci)s, %(conf)s, %(mo)s,
                               %(p)s, now() + (%(days)s || ' days')::interval)
                       on conflict (tenant_id, machine_key, question_key, chunk_key) do update
                         set answer_local = excluded.answer_local, sources = excluded.sources,
                             citations = excluded.citations, confidence = excluded.confidence,
                             model = excluded.model, provider = excluded.provider,
                             created_at = now(), expires_at = excluded.expires_at""",
                    {"t": tenant_id, "m": machine, "q": q_key, "c": c_key, "a": answer_local,
                     "s": Jsonb(sources), "ci": Jsonb(citations), "conf": confidence,
                     "mo": model, "p": provider, "days": str(self.ttl_days)},
                )
            conn.commit()

    def invalidate_tenant(self, tenant_id: str) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from answer_cache where tenant_id = %(t)s", {"t": tenant_id})
                n = cur.rowcount
            conn.commit()
            return n
