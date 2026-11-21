"""Hybrid search: vector + keyword + graph retrievers merged with RRF.

All queries filter tenant_id explicitly (the backend connects privileged; RLS
does not protect these queries). Tunables sit at the top for eval tuning.

Round-trip budget (remote DB, ~40 ms RTT, payload transfer ~6-9 ms/KB):
- one cached prep query (glossary + machines, TTL) — amortised to 0 RT for
  PREP_CACHE_TTL seconds;
- ONE search query that runs every retriever as a CTE, computes the RRF score
  in SQL, applies the same-machine bonus and the max-per-source cap, and
  returns only the final k rows — with text — in a single round trip
  (autocommit read: no BEGIN/COMMIT packets).

The query vector is rounded to 5 decimals to shrink the upload payload
(bge-small vectors are unit-norm; 1e-5 precision does not change the ranking).
"""

from __future__ import annotations

import logging
import re
import time

import numpy as np

from app.core.db import db_read
from app.core.errors import ApiError
from app.services import embeddings, knowledge
from app.services import reranker as reranker_mod

# ---- tunables (search_eval may adjust) --------------------------------------
RRF_K = 60
GRAPH_MIN_SIM = 0.45
GRAPH_LOG_MIN_SIM = 0.35
SAME_MACHINE_BONUS = 0.004
VECTOR_TOP = 30
KEYWORD_TOP = 30
TABLE_TOP = 8       # manual tables (specs, intervals, error codes) are read as prose otherwise
TABLE_FLOOR = 0.55  # cosine floor for the table retriever (spec rows are short)
TABLE_WEIGHT = 0.25  # a boost, not a full retriever vote: must not push out a better record
GRAPH_SYMPTOMS = 3
GRAPH_RECORDS = 10
GRAPH_LOGS = 5
CANDIDATES = 20  # hydrated rows when the reranker is on
MAX_PER_SOURCE = 6  # candidate cap per document; with rerank on, enough manual pages must reach it
PREP_CACHE_TTL = 60  # seconds; glossary/machines change rarely
# Cosine floor for the vector retriever: nonsense queries top out ~0.59 while the
# weakest neighbours of real queries measure ~0.66+ (bge-small-en-v1.5). Below the
# floor a result is noise, so the vector retriever skips it entirely.
VEC_FLOOR = 0.62

logger = logging.getLogger("kaarigar.search")

CODE_TOKEN_RE = re.compile(r"\b([A-Za-z]{1,6}[\s-]?\d{1,4})\b|\b(\d{3,4})\b")

_prep_cache: dict[str, tuple[float, dict]] = {}


def _code_variants(q: str) -> list[str]:
    """'E05 alarm' → ['E05','E-05']; 'e 05' → ['E-05']; 'HP-07' → ['HP-07','HP07']."""
    out: list[str] = []
    for m in CODE_TOKEN_RE.finditer(q):
        tok = (m.group(1) or m.group(2) or "").strip()
        if not tok:
            continue
        compact = tok.replace(" ", "").replace("-", "").upper()
        letters = re.match(r"^([A-Z]*)(\d+)$", compact)
        if letters and letters.group(1):
            pre, digits = letters.groups()
            out.extend((f"{pre}-{digits}", compact))
        else:
            out.append(compact)
    seen: set[str] = set()
    return [v for v in out if not (v in seen or seen.add(v))]


_SEARCH_SQL = """
with qtsq as (
  select to_tsquery('simple',
    coalesce(nullif(array_to_string(tsvector_to_array(to_tsvector('english', %(qx)s)), ' | '), ''),
             'zzzznomatch')) as tsq
),
sym as (
  select s.id, s.name,
         greatest(word_similarity(s.name, %(qx)s),
                  coalesce((select max(word_similarity(a, %(qx)s)) from unnest(s.aliases) a), 0)) as sim
  from symptoms s
  where s.tenant_id = %(tenant)s
  order by sim desc
  limit %(nsym)s
),
vec as (
  select c.id, row_number() over () as r
  from (
    select c.id
    from chunks c
    where c.tenant_id = %(tenant)s
      and (%(model)s::uuid is null or c.model_id = %(model)s)
      and c.embedding is not null
      and 1 - (c.embedding <=> %(qvec)s) >= %(vecfloor)s
    order by c.embedding <=> %(qvec)s
    limit %(nvec)s
  ) c
),
kcodes as (
  select c.id, row_number() over () as r
  from (
    select c.id
    from chunks c
    where c.tenant_id = %(tenant)s
      and (%(model)s::uuid is null or c.model_id = %(model)s)
      and c.text ilike any(%(codes_like)s)
    order by (select coalesce(sum(
                (length(lower(c.text)) - length(replace(lower(c.text), lower(v), ''))) / length(v)), 0)
              from unnest(%(codes)s::text[]) v) desc, c.id
    limit %(nkw)s
  ) c
),
kwords as (
  select c.id, row_number() over () as r
  from (
    select c.id, ts_rank_cd(c.tsv, q.tsq) as score
    from chunks c, qtsq q
    where c.tenant_id = %(tenant)s
      and (%(model)s::uuid is null or c.model_id = %(model)s)
      and c.tsv @@ q.tsq
    order by score desc, c.id
    limit %(nkw)s
  ) c
),
grec as (
  select c.id, row_number() over () as r
  from (
    select c.id
    from chunks c
    join repair_records rr on rr.id = c.source_id and c.source_type = 'record'
    join (select * from sym where sim >= %(min)s) s on s.id = rr.symptom_id
    left join machines m on m.id = rr.machine_id
    where c.tenant_id = %(tenant)s
      and rr.status = 'approved'
      and (%(model)s::uuid is null or m.model_id = %(model)s)
    order by coalesce(rr.machine_id = %(machine)s, false) desc, s.sim desc, rr.created_at desc
    limit %(nrec)s
  ) c
),
glogs as (
  select c.id, row_number() over () as r
  from (
    select c.id
    from chunks c
    join maintenance_logs l on l.id = c.source_id and c.source_type = 'log'
    where c.tenant_id = %(tenant)s
      and %(machine)s::uuid is not null
      and c.machine_id = %(machine)s::uuid
      and (word_similarity(coalesce(l.fault, ''), %(qx)s) >= %(lmin)s
           or word_similarity(coalesce(l.action, ''), %(qx)s) >= %(lmin)s)
    order by l.date desc nulls last, c.id
    limit %(nlogs)s
  ) c
),
tbl as (
  -- Table rows are 'Header: value | Header: value'. A spec/interval/code row often
  -- answers a question better than a paragraph that merely shares its words.
  select c.id, row_number() over () as r
  from (
    select c.id
    from chunks c
    where c.tenant_id = %(tenant)s
      and (%(model)s::uuid is null or c.model_id = %(model)s)
      and c.embedding is not null
      and c.text like '%% | %%'
      and coalesce(c.section, '') not ilike '%%contents%%'   -- TOC lines look like table rows
      and 1 - (c.embedding <=> %(qvec)s) >= %(tblfloor)s
    order by c.embedding <=> %(qvec)s
    limit %(ntbl)s
  ) c
),
allc as (
  select id, 'v' ret, r from vec
  union all select id, 'kc', r from kcodes
  union all select id, 'kw', r from kwords
  union all select id, 'gr', r from grec
  union all select id, 'gl', r from glogs
  union all select id, 'tb', r from tbl
),
scored as (
  select a.id,
         sum((case when a.ret = 'tb' then %(tblw)s else 1.0 end)::float8 / (%(rrfk)s + a.r)) as base,
         jsonb_object_agg(a.ret, a.r) as ranks
  from allc a
  group by a.id
),
ranked as (
  select s.id, s.ranks,
         s.base + case when %(machine)s::uuid is not null and c.machine_id = %(machine)s::uuid
                       then %(bonus)s else 0 end as score,
         c.source_type, c.source_id, c.machine_id, c.section, c.page, c.text, c.meta,
         mm.model, d.title as doc_title, m.code as machine_code,
         u.name as author, rr.created_at as record_date, ml.date as log_date
  from scored s
  join chunks c on c.id = s.id and c.tenant_id = %(tenant)s
  left join machine_models mm on mm.id = c.model_id
  left join documents d on d.id = c.source_id and c.source_type = 'manual'
  left join repair_records rr on rr.id = c.source_id and c.source_type = 'record'
  left join users u on u.id = rr.author_id
  left join maintenance_logs ml on ml.id = c.source_id and c.source_type = 'log'
  left join machines m on m.id = c.machine_id
),
final as (
  select *, row_number() over (partition by source_type, source_id order by score desc, id) as rn
  from ranked
)
select f.id, f.score, f.ranks, f.source_type, f.source_id, f.machine_id,
       f.section, f.page, f.text, f.meta, f.model, f.doc_title, f.machine_code,
       f.author, f.record_date, f.log_date,
       (select coalesce(json_agg(json_build_object('name', name, 'sim', sim)), '[]') from sym) as symptoms
from final f
where f.rn <= %(maxsrc)s
order by f.score desc, f.id
limit %(kfinal)s
"""

# column indexes of the search row
C_ID, C_SCORE, C_RANKS, C_STYPE, C_SID, C_MID = 0, 1, 2, 3, 4, 5
C_SECTION, C_PAGE, C_TEXT, C_META = 6, 7, 8, 9
C_MODEL, C_DOC_TITLE, C_MCODE, C_AUTHOR, C_REC_DATE, C_LOG_DATE, C_SYMPTOMS = 10, 11, 12, 13, 14, 15, 16


def _friendly_ranks(rank_map: dict) -> dict[str, int]:
    """{'v': 1, 'kc': 2, 'kw': 5, 'gr': 3, 'tb': 2} → {'vector': 1, 'keyword': 2, 'graph': 3, 'table': 2}."""
    out: dict[str, int] = {}
    if rank_map.get("v"):
        out["vector"] = int(rank_map["v"])
    kw = [int(rank_map[t]) for t in ("kc", "kw") if rank_map.get(t)]
    if kw:
        out["keyword"] = min(kw)
    gr = [int(rank_map[t]) for t in ("gr", "gl") if rank_map.get(t)]
    if gr:
        out["graph"] = min(gr)
    if rank_map.get("tb"):
        out["table"] = int(rank_map["tb"])
    return out


def _title_for(row: dict) -> str:
    stype = row["source_type"]
    if stype == "manual":
        return f"{row['doc_title']} · p.{row['page']}" if row["doc_title"] else "Manual"
    if stype == "record":
        date = row["record_date"].strftime("%-d %b %Y") if row["record_date"] else ""
        return "Repair record · " + " · ".join(x for x in [row["machine_code"], date, row["author"]] if x)
    date = row["log_date"].strftime("%-d %b %Y") if row["log_date"] else ""
    return "Breakdown log · " + " · ".join(x for x in [row["machine_code"], date] if x)


def search(
    tenant_id: str,
    q: str,
    machine_code: str | None = None,
    k: int = 8,
    rerank: bool | None = None,
    debug: bool = False,
) -> dict:
    if not embeddings.ready():
        raise ApiError(503, "embed_not_ready", "The embedding model is still loading. Try again shortly.")
    started = time.perf_counter()
    q = (q or "").strip()
    if not (2 <= len(q) <= 300):
        raise ApiError(422, "validation_error", "q must be 2-300 characters.")

    # prep (cached): glossary + machine scope, one query per TTL window
    now = time.time()
    cached = _prep_cache.get(tenant_id)
    if cached is None or cached[0] < now:
        with db_read() as conn:
            row = conn.execute(
                """select
                     (select coalesce(json_object_agg(term, meaning), '{}')::jsonb
                        from glossary where tenant_id = %(tenant)s),
                     (select coalesce(json_agg(json_build_object(
                          'id', m.id, 'model_id', m.model_id, 'code', m.code)), '[]')::jsonb
                        from machines m where m.tenant_id = %(tenant)s)""",
                {"tenant": tenant_id},
            ).fetchone()
        _prep_cache[tenant_id] = (now + PREP_CACHE_TTL, {"glossary": row[0], "machines": row[1]})
        cached = _prep_cache[tenant_id]
    glossary: dict[str, str] = cached[1]["glossary"]
    machines: list[dict] = cached[1]["machines"]

    machine = None
    if machine_code:
        for m in machines:
            if m["code"] == machine_code:
                machine = {"id": str(m["id"]),
                           "model_id": str(m["model_id"]) if m["model_id"] else None,
                           "code": m["code"]}
                break
        if machine is None:
            raise ApiError(404, "unknown_machine", f"No machine '{machine_code}' in this plant.")
    machine_id = machine["id"] if machine else None
    model_id = machine["model_id"] if machine else None

    qx, glossary_used = knowledge.expand_terms(q, glossary)
    qvec = np.round(embeddings.embed_query(qx), 4)
    use_rerank = reranker_mod.enabled(rerank) and embeddings.rerank_ready()

    params = {
        "tenant": tenant_id,
        "model": model_id,
        "machine": machine_id,
        "qx": qx,
        "qvec": qvec,
        "codes": _code_variants(q),
        "codes_like": [f"%{v}%" for v in _code_variants(q)] or ["{nonematch}"],
        "rrfk": RRF_K,
        "bonus": SAME_MACHINE_BONUS,
        "nvec": VECTOR_TOP,
        "nkw": KEYWORD_TOP,
        "nsym": GRAPH_SYMPTOMS,
        "min": GRAPH_MIN_SIM,
        "lmin": GRAPH_LOG_MIN_SIM,
        "nrec": GRAPH_RECORDS,
        "nlogs": GRAPH_LOGS,
        "maxsrc": MAX_PER_SOURCE,
        "ntbl": TABLE_TOP,
        "tblfloor": TABLE_FLOOR,
        "tblw": TABLE_WEIGHT,
        "kfinal": CANDIDATES if use_rerank else k,
        "vecfloor": VEC_FLOOR,
    }
    with db_read() as conn:
        rows = conn.execute(_SEARCH_SQL, params).fetchall()

    symptoms: list[dict] = rows[0][C_SYMPTOMS] if rows else []
    candidates: list[dict] = []
    for r in rows:
        stype = r[C_STYPE]
        candidates.append(
            {
                "id": str(r[C_ID]),
                "score": float(r[C_SCORE]),
                "ranks": _friendly_ranks(r[C_RANKS] or {}),
                "label": {"record": "E", "manual": "M", "log": "H"}.get(stype, "?"),
                "source_type": stype,
                "source_id": str(r[C_SID]),
                "machine_id": str(r[C_MID]) if r[C_MID] else None,
                "section": r[C_SECTION],
                "page": r[C_PAGE],
                "text": r[C_TEXT],
                "meta": r[C_META] or {},
                "model": r[C_MODEL],
                "doc_title": r[C_DOC_TITLE],
                "machine_code": r[C_MCODE],
                "author": r[C_AUTHOR],
                "record_date": r[C_REC_DATE],
                "log_date": r[C_LOG_DATE],
                "same_machine": bool(machine_id) and str(r[C_MID]) == machine_id,
                "title": "",
            }
        )
    for c in candidates:
        c["title"] = _title_for(c)

    confidence = None
    if use_rerank and candidates:
        reranker_mod.rerank(qx, candidates)
        confidence = candidates[0].get("confidence")

    results = []
    for c in candidates[:k]:
        results.append(
            {
                "label": c["label"],
                "source_type": c["source_type"],
                "source_id": c["source_id"],
                "chunk_id": c["id"],
                "title": c["title"],
                "section": c["section"],
                "page": c["page"],
                "text": c["text"],
                "score": round(c["score"], 4),
                "rerank_score": c.get("rerank_score"),
                "ranks": c["ranks"],
                "same_machine": c["same_machine"],
                "meta": c["meta"],
                "model": c["model"],
                "machine_code": c["machine_code"],
            }
        )

    took_ms = int((time.perf_counter() - started) * 1000)
    out = {
        "query": q,
        "expanded_query": qx,
        "machine": machine["code"] if machine else None,
        "took_ms": took_ms,
        "confidence": confidence,
        "results": results,
    }
    if debug:
        ret_lists: dict[str, list] = {"vector": [], "keyword": [], "graph": [], "table": []}
        for c in candidates:
            rm = c.get("ranks") or {}
            base = {
                "title": c["title"],
                "source_type": c["source_type"],
                "seed_key": (c.get("meta") or {}).get("seed_key"),
            }
            for dst in ("vector", "keyword", "graph", "table"):
                if rm.get(dst):
                    ret_lists[dst].append({**base, "rank": int(rm[dst])})
        for dst in ret_lists:
            ret_lists[dst].sort(key=lambda x: x["rank"])
        out["debug"] = {
            "vector": ret_lists["vector"],
            "keyword": ret_lists["keyword"],
            "graph": ret_lists["graph"],
            "table": ret_lists["table"],
            "symptoms_matched": [
                {"name": s["name"], "sim": round(float(s["sim"]), 3)} for s in symptoms
            ],
            "glossary_used": glossary_used,
        }
    return out
