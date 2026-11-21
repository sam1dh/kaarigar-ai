"""Repair-record chunks and glossary query expansion."""

from __future__ import annotations

import json
import re

from app.core.config import get_settings
from app.core.db import db
from app.services import embeddings


def record_chunk_text(record: dict) -> str:
    """Machine HP-07 (HPX-200 hydraulic press). Symptom: … Cause: … Fix: … Safety: … Expert notes: …"""
    machine = record.get("machine") or {}
    parts = [f"Machine {machine.get('code', '')}"]
    model_label = " ".join(x for x in [machine.get("model"), machine.get("type")] if x)
    if model_label:
        parts[0] += f" ({model_label})"
    text = " ".join(parts) + "."
    if record.get("symptom"):
        text += f" Symptom: {record['symptom']}"
    if record.get("cause"):
        text += f" Cause: {record['cause']}"
    if record.get("fix"):
        text += f" Fix: {record['fix']}"
    if record.get("safety_note"):
        text += f" Safety: {record['safety_note']}"
    if record.get("expert_notes"):
        text += f" Expert notes: {record['expert_notes']}"
    return text


def _machine_row(conn, machine_id) -> dict:
    row = conn.execute(
        """select m.id, m.code, m.name, mm.model, mm.type, m.model_id
           from machines m left join machine_models mm on mm.id = m.model_id
           where m.id = %s""",
        (machine_id,),
    ).fetchone()
    if not row:
        return {}
    return {"id": str(row[0]), "code": row[1], "name": row[2], "model": row[3], "type": row[4], "model_id": str(row[5]) if row[5] else None}


def rebuild_record_chunks(record_id: str) -> None:
    """Delete + reinsert the record's chunk. Only approved records keep chunks."""
    with db() as conn:
        row = conn.execute(
            """select r.tenant_id, r.machine_id, r.symptom_id, r.cause_id, r.fix_id,
                      r.safety_note, r.fields, r.status, r.transcript_en, r.archived_at
               from repair_records r where r.id = %s""",
            (record_id,),
        ).fetchone()
    if not row:
        return
    (tenant_id, machine_id, symptom_id, cause_id, fix_id,
     safety_note, fields, status, transcript_en, archived_at) = row

    with db() as conn:
        conn.execute(
            "delete from chunks where source_type = 'record' and source_id = %s",
            (record_id,),
        )
    if status != "approved" or archived_at is not None:
        return

    with db() as conn:
        symptom = conn.execute("select name from symptoms where id = %s", (symptom_id,)).fetchone()
        cause = conn.execute("select name from causes where id = %s", (cause_id,)).fetchone()
        fix = conn.execute("select name from fixes where id = %s", (fix_id,)).fetchone()
        machine = _machine_row(conn, machine_id) if machine_id else {}

    fields = fields or {}
    record = {
        "machine": machine,
        "symptom": symptom[0] if symptom else fields.get("symptom"),
        "cause": cause[0] if cause else fields.get("cause"),
        "fix": fix[0] if fix else fields.get("fix"),
        "safety_note": safety_note or fields.get("safety_note"),
        "expert_notes": transcript_en or fields.get("expert_notes"),
    }
    text = record_chunk_text(record)
    vec = embeddings.embed_passages([text])[0]

    meta = {}
    if fields.get("seed_key"):
        meta["seed_key"] = fields["seed_key"]
    meta["embed_model"] = get_settings().embed_model
    with db() as conn:
        conn.execute(
            """insert into chunks
               (tenant_id, source_type, source_id, model_id, machine_id, text, embedding, chunk_index, meta)
               values (%s, 'record', %s, %s, %s, %s, %s, 0, %s)""",
            (
                tenant_id,
                record_id,
                machine.get("model_id"),
                machine_id,
                text,
                list(map(float, vec)),
                json.dumps(meta),
            ),
        )


def expand_terms(q: str, glossary: dict[str, str]) -> tuple[str, list[str]]:
    """'pump thak thak' → 'pump thak thak (knocking sound)'. Whole word, also spaced ('thak thak')."""
    if not q or not q.strip():
        return q, []
    used: list[str] = []
    expanded = q
    for term, meaning in glossary.items():
        if not term or not meaning:
            continue
        base = term.strip().lower()
        variants = [re.escape(base)]
        if "-" in base:
            variants.append(re.escape(base.replace("-", " ")))
        for var in variants:
            pattern = rf"(?<![A-Za-z0-9])({var})(?![A-Za-z0-9])"
            if re.search(pattern, expanded, flags=re.IGNORECASE):
                expanded = re.sub(
                    pattern,
                    lambda m, t=term.strip(), mn=meaning.strip(): f"{m.group(1)} ({mn})",
                    expanded,
                    flags=re.IGNORECASE,
                )
                if term.strip() not in used:
                    used.append(term.strip())
                break
    return expanded, used


def expand_query(q: str, tenant_id: str) -> tuple[str, list[str]]:
    """DB-backed variant (fetches the tenant's glossary, then expands)."""
    if not q or not q.strip():
        return q, []
    with db() as conn:
        rows = conn.execute(
            "select term, meaning from glossary where tenant_id = %s",
            (tenant_id,),
        ).fetchall()
    return expand_terms(q, {r[0]: r[1] for r in rows if r[1]})


def reembed_tenant(tenant_id: str) -> None:
    """Re-embed every chunk of the tenant (after EMBED_MODEL changes)."""
    with db() as conn:
        rows = conn.execute(
            "select id, text from chunks where tenant_id = %s", (tenant_id,)
        ).fetchall()
    ids = [str(r[0]) for r in rows]
    texts = [r[1] for r in rows]
    s = get_settings()
    for start in range(0, len(texts), embeddings.BATCH):
        batch = texts[start : start + embeddings.BATCH]
        vectors = embeddings.embed_passages(batch)
        with db() as conn:
            for cid, vec in zip(ids[start : start + embeddings.BATCH], vectors, strict=True):
                conn.execute(
                    "update chunks set embedding = %s, meta = meta || %s::jsonb where id = %s",
                    (list(map(float, vec)), json.dumps({"embed_model": s.embed_model}), cid),
                )
