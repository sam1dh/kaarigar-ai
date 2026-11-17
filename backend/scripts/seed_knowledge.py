"""Seed Phase 1 knowledge for the demo plant (shree). Run after seed.py.

  python -m scripts.seed_knowledge [--reset]

Idempotent: glossary/symptoms/causes/fixes upserted by natural key, records by
fields->>'seed_key', manuals skipped when already ready, log import skipped when
the same file_hash was already imported. --reset first deletes everything this
script created, then rebuilds.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yaml

from app.core.config import get_settings
from app.core.db import db
from app.services import embeddings, knowledge, log_import, pdf_ingest, storage
from app.services.column_mapping import rules_mapping

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PLANT_SLUG = "shree"
LOG_FILE = "shree_breakdown_log.xlsx"

MANUALS = [
    # (model, title, file name)
    ("HPX-200", "HPX-200 Service Manual", "HPX-200_service_manual.pdf"),
    ("CL-40", "CL-40 Operator Manual", "CL-40_operator_manual.pdf"),
    ("AC-75", "AC-75 Service Manual", "AC-75_service_manual.pdf"),
]


def _load_seed() -> dict:
    with open(os.path.join(DATA_DIR, "knowledge_seed.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _wait_for_embed(timeout: int = 180) -> None:
    """First run downloads ~70 MB into .cache/fastembed."""
    if embeddings.ready():
        return
    print("Waiting for the embedding model to load (first run downloads ~70 MB)...")
    embeddings.wait_ready(timeout)
    print(f"Embedding model ready ({get_settings().embed_model}).")


# ===== reset =====

def reset(tenant_id: str) -> None:
    # 1. seed records (+ their chunks)
    with db() as conn:
        conn.execute(
            """delete from chunks where source_type = 'record' and source_id in
               (select id from repair_records where tenant_id = %s and source = 'seed')""",
            (tenant_id,),
        )
        n = conn.execute(
            "delete from repair_records where tenant_id = %s and source = 'seed' returning id",
            (tenant_id,),
        ).rowcount
    print(f"  removed {n} seed records")

    # 2. the 3 manuals (+ chunks + storage files)
    titles = tuple(t for _, t, _ in MANUALS)
    with db() as conn:
        rows = conn.execute(
            "select id, file_path from documents where tenant_id = %s and title = any(%s)",
            (tenant_id, list(titles)),
        ).fetchall()
        for doc_id, file_path in rows:
            conn.execute("delete from chunks where source_type = 'manual' and source_id = %s", (doc_id,))
            conn.execute("delete from documents where id = %s", (doc_id,))
            storage.delete(file_path)
    print(f"  removed {len(rows)} documents")

    # 3. the log import (+ its logs + chunks)
    with db() as conn:
        imports = conn.execute(
            "select id from log_imports where tenant_id = %s and file_name = %s",
            (tenant_id, LOG_FILE),
        ).fetchall()
        ids = [str(r[0]) for r in imports]
        if ids:
            conn.execute(
                """delete from chunks where source_type = 'log' and source_id in
                   (select id from maintenance_logs where import_id = any(%s))""",
                (ids,),
            )
            n_logs = conn.execute(
                "delete from maintenance_logs where import_id = any(%s) returning id", (ids,)
            ).rowcount
            conn.execute("delete from log_imports where id = any(%s)", (ids,))
            print(f"  removed 1 log import with {n_logs} log rows")


# ===== knowledge tables =====

def upsert_knowledge(tenant_id: str, seed: dict) -> tuple[dict, dict, dict]:
    symptom_ids: dict[str, str] = {}
    cause_ids: dict[str, str] = {}
    fix_ids: dict[str, str] = {}
    with db() as conn:
        for g in seed.get("glossary", []):
            conn.execute(
                """insert into glossary (tenant_id, term, meaning, keep_in_english)
                   values (%s, %s, %s, %s)
                   on conflict (tenant_id, term)
                   do update set meaning = excluded.meaning, keep_in_english = excluded.keep_in_english""",
                (tenant_id, g["term"], g["meaning"], bool(g.get("keep_in_english"))),
            )
        for s in seed.get("symptoms", []):
            row = conn.execute(
                """insert into symptoms (tenant_id, name, aliases) values (%s, %s, %s)
                   on conflict (tenant_id, name)
                   do update set aliases = excluded.aliases
                   returning id""",
                (tenant_id, s["name"], list(s.get("aliases") or [])),
            ).fetchone()
            symptom_ids[s["key"]] = str(row[0])
        for c in seed.get("causes", []):
            row = conn.execute(
                """insert into causes (tenant_id, name) values (%s, %s)
                   on conflict (tenant_id, name) do update set name = excluded.name
                   returning id""",
                (tenant_id, c["name"]),
            ).fetchone()
            cause_ids[c["key"]] = str(row[0])
        for f in seed.get("fixes", []):
            row = conn.execute(
                """insert into fixes (tenant_id, name) values (%s, %s)
                   on conflict (tenant_id, name) do update set name = excluded.name
                   returning id""",
                (tenant_id, f["name"]),
            ).fetchone()
            fix_ids[f["key"]] = str(row[0])
    print(
        f"  glossary {len(seed.get('glossary', []))}, symptoms {len(symptom_ids)}, "
        f"causes {len(cause_ids)}, fixes {len(fix_ids)}"
    )
    return symptom_ids, cause_ids, fix_ids


# ===== records =====

def seed_records(tenant_id: str, seed: dict, symptom_ids: dict, cause_ids: dict, fix_ids: dict) -> int:
    with db() as conn:
        author = conn.execute(
            "select id from users where tenant_id = %s and employee_id = %s",
            (tenant_id, seed["author_employee_id"]),
        ).fetchone()
        reviewer = conn.execute(
            "select id from users where tenant_id = %s and role = 'supervisor' limit 1",
            (tenant_id,),
        ).fetchone()
        machines = conn.execute(
            "select code, id from machines where tenant_id = %s", (tenant_id,)
        ).fetchall()
    if not author or not reviewer:
        raise RuntimeError("Author SH-0107 or the supervisor is missing — run scripts/seed.py first.")
    machine_ids = {code: str(mid) for code, mid in machines}

    n = 0
    for rec in seed.get("records", []):
        key = rec["key"]
        machine_id = machine_ids.get(rec["machine"])
        if not machine_id:
            print(f"  !! record {key}: unknown machine {rec['machine']}, skipped")
            continue
        created = dt.datetime.combine(rec["date"], dt.time(10, 30))
        fields = {
            "seed_key": key,
            "symptom": rec.get("symptom"),
            "cause": rec.get("cause"),
            "fix": rec.get("fix"),
        }
        with db() as conn:
            existing = conn.execute(
                "select id from repair_records where tenant_id = %s and fields->>'seed_key' = %s",
                (tenant_id, key),
            ).fetchone()
            if existing:
                conn.execute(
                    """update repair_records set
                         machine_id = %s, author_id = %s, transcript_en = %s,
                         symptom_id = %s, cause_id = %s, fix_id = %s, safety_note = %s,
                         fields = %s::jsonb, status = 'approved', reviewed_by = %s,
                         reviewed_at = %s, created_at = %s
                       where id = %s""",
                    (
                        machine_id, author[0], rec.get("transcript_en"),
                        symptom_ids.get(rec.get("symptom")), cause_ids.get(rec.get("cause")),
                        fix_ids.get(rec.get("fix")), rec.get("safety_note"),
                        json.dumps(fields), reviewer[0], created, created, existing[0],
                    ),
                )
                record_id = str(existing[0])
            else:
                row = conn.execute(
                    """insert into repair_records
                       (tenant_id, machine_id, author_id, transcript_en, symptom_id, cause_id,
                        fix_id, safety_note, fields, status, reviewed_by, reviewed_at,
                        source, created_at)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'approved', %s, %s,
                               'seed', %s)
                       returning id""",
                    (
                        tenant_id, machine_id, author[0], rec.get("transcript_en"),
                        symptom_ids.get(rec.get("symptom")), cause_ids.get(rec.get("cause")),
                        fix_ids.get(rec.get("fix")), rec.get("safety_note"),
                        json.dumps(fields), reviewer[0], created, created,
                    ),
                ).fetchone()
                record_id = str(row[0])
        knowledge.rebuild_record_chunks(record_id)
        n += 1
    print(f"  records {n} (approved, searchable)")
    return n


# ===== manuals =====

def seed_manuals(tenant_id: str, supe_user_id: str) -> int:
    with db() as conn:
        models = conn.execute(
            "select model, id from machine_models where tenant_id = %s", (tenant_id,)
        ).fetchall()
    model_ids = dict(models)

    ready = 0
    for model, title, fname in MANUALS:
        model_id = model_ids.get(model)
        if not model_id:
            print(f"  !! {title}: model {model} not found, skipped")
            continue
        with db() as conn:
            existing = conn.execute(
                """select id, status from documents
                   where tenant_id = %s and title = %s and model_id = %s
                   order by created_at desc limit 1""",
                (tenant_id, title, model_id),
            ).fetchone()
        if existing and existing[1] == "ready":
            ready += 1
            print(f"  {title}: already ready, skipped")
            continue
        if existing:
            with db() as conn:
                conn.execute("delete from chunks where source_type = 'manual' and source_id = %s", (existing[0],))
                row = conn.execute(
                    "delete from documents where id = %s returning file_path", (existing[0],)
                ).fetchone()
            if row and row[0]:
                storage.delete(row[0])

        data = open(os.path.join(DATA_DIR, "manuals", fname), "rb").read()
        document_id = str(uuid.uuid4())
        path = f"documents/{tenant_id}/{document_id}.pdf"
        storage.upload(path, data, "application/pdf")
        with db() as conn:
            conn.execute(
                """insert into documents
                   (id, tenant_id, model_id, title, type, file_path, status, file_hash, created_by)
                   values (%s, %s, %s, %s, 'manual', %s, 'uploaded', %s, %s)""",
                (document_id, tenant_id, model_id, title, path, hashlib.sha256(data).hexdigest(), supe_user_id),
            )
        pdf_ingest.ingest_document(document_id)
        with db() as conn:
            row = conn.execute(
                "select status, quality_notes from documents where id = %s", (document_id,)
            ).fetchone()
        if row and row[0] == "ready":
            ready += 1
            notes = row[1] or ""
            print(f"  {title}: ready ({notes.splitlines() or 'no quality notes'})")
        else:
            print(f"  !! {title}: status {row and row[0]}")
    return ready


# ===== breakdown log =====

def seed_log_import(tenant_id: str, supe_user_id: str) -> tuple[int, int]:
    data = open(os.path.join(DATA_DIR, LOG_FILE), "rb").read()
    file_hash = hashlib.sha256(data).hexdigest()

    with db() as conn:
        done = conn.execute(
            """select id from log_imports
               where tenant_id = %s and file_hash = %s and status = 'done' limit 1""",
            (tenant_id, file_hash),
        ).fetchone()
    if done:
        row = None
        with db() as conn:
            row = conn.execute(
                "select rows_ok, rows_skipped from log_imports where id = %s", (done[0],)
            ).fetchone()
        print(f"  log import: already imported ({row[0]} rows), skipped")
        return row[0], row[1]

    parsed = log_import.analyse(tenant_id, LOG_FILE, data)
    mapping = rules_mapping(parsed["columns"])
    import_id = str(uuid.uuid4())
    path = f"imports/{tenant_id}/{import_id}.xlsx"
    storage.upload(
        path, data,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    detected = {
        "header_row": parsed["header_row"],
        "columns": parsed["columns"],
        "sample_rows": parsed["sample_rows"],
        "total_rows": parsed["total_rows"],
        "mapping_source": "rules",
    }
    with db() as conn:
        conn.execute(
            """insert into log_imports
               (id, tenant_id, file_path, column_mapping, status, file_name, file_hash, detected, created_by)
               values (%s, %s, %s, %s::jsonb, 'mapping', %s, %s, %s::jsonb, %s)""",
            (
                import_id, tenant_id, path, json.dumps(mapping),
                LOG_FILE, file_hash, json.dumps(detected), supe_user_id,
            ),
        )
    log_import.import_rows(import_id, tenant_id, mapping)
    with db() as conn:
        row = conn.execute(
            "select rows_ok, rows_skipped from log_imports where id = %s", (import_id,)
        ).fetchone()
    print(f"  log import: {row[0]} imported, {row[1]} skipped (mapping = rules)")
    return row[0], row[1]


# ===== main =====

def main() -> None:
    ap = argparse.ArgumentParser(description="Seed Phase 1 knowledge for the demo plant.")
    ap.add_argument("--reset", action="store_true", help="delete this script's artifacts first")
    args = ap.parse_args()

    started = time.time()
    _wait_for_embed()

    with db() as conn:
        tenant = conn.execute("select id from tenants where slug = %s", (PLANT_SLUG,)).fetchone()
        if not tenant:
            raise SystemExit(f"Plant '{PLANT_SLUG}' not found — run scripts/seed.py first.")
        tenant_id = str(tenant[0])
        supe = conn.execute(
            "select id from users where tenant_id = %s and role = 'supervisor' limit 1",
            (tenant_id,),
        ).fetchone()
        if not supe:
            raise SystemExit("Supervisor user missing — run scripts/seed.py first.")
    supe_id = str(supe[0])
    print(f"Plant {PLANT_SLUG} ({tenant_id[:8]}…)")

    seed = _load_seed()
    if args.reset:
        print("Resetting Phase 1 artifacts…")
        reset(tenant_id)

    print("Knowledge tables:")
    symptom_ids, cause_ids, fix_ids = upsert_knowledge(tenant_id, seed)

    print("Repair records:")
    n_records = seed_records(tenant_id, seed, symptom_ids, cause_ids, fix_ids)

    print("Manuals:")
    n_docs = seed_manuals(tenant_id, supe_id)

    print("Breakdown log:")
    n_ok, n_skip = seed_log_import(tenant_id, supe_id)

    # summary
    with db() as conn:
        chunk_rows = conn.execute(
            "select source_type, count(*) from chunks where tenant_id = %s group by source_type",
            (tenant_id,),
        ).fetchall()
    chunks = {r[0]: r[1] for r in chunk_rows}
    elapsed = time.time() - started
    print(
        f"\nSummary: records {n_records} · documents {n_docs}/3 ready · "
        f"logs {n_ok} imported / {n_skip} skipped · "
        f"chunks: manual {chunks.get('manual', 0)}, record {chunks.get('record', 0)}, "
        f"log {chunks.get('log', 0)} · {elapsed:.1f}s"
    )


if __name__ == "__main__":
    main()
