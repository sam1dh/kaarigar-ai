"""Excel/CSV → maintenance_logs → chunks.

Step A analyse() runs synchronously on upload (<2 s).
Step B import_rows() runs as a job after the admin confirms the mapping.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import logging
import re

import openpyxl

from app.core.config import get_settings
from app.core.db import db
from app.services import embeddings, jobs, storage
from app.services.column_mapping import suggest_mapping

logger = logging.getLogger("kaarigar.logs")

DATE_TEXT_RE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$")

# fields the admin must map before import can run
_REQUIRED = ["machine_code", "date", "fault"]


# ---------- normalisation helpers (unit-tested) ----------

def normalise_code(raw: str) -> str:
    """'HP-07', 'HP 07', 'hp7' → 'HP7'; 'CNC 3' → 'CNC3'; 'AC-01' → 'AC1'."""
    code = re.sub(r"[^A-Za-z0-9]", "", str(raw)).upper()
    m = re.match(r"^([A-Z]*)(\d*)$", code)
    if not m:
        return code
    letters, digits = m.groups()
    if digits:
        digits = digits.lstrip("0") or "0"
    return letters + digits


def parse_date(value) -> str | None:
    """Excel dates as-is; text is day-first. Returns ISO 'YYYY-MM-DD' or None."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # openpyxl usually converts, but a raw serial can slip through
        try:
            base = dt.date(1899, 12, 30)
            return (base + dt.timedelta(days=int(value))).isoformat()
        except (ValueError, OverflowError):
            return None
    m = DATE_TEXT_RE.match(str(value).strip())
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100:
        year += 2000
    if not (1 <= day <= 31 and 1 <= month <= 12 and 1990 <= year <= 2100):
        return None
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_downtime(value) -> int | None:
    """40 → 40; '45 min' → 45; '1.5 hr' → 90; '2 hours' → 120; '1:15' → 75; '' → None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(round(value)) if value == value else None  # NaN guard
    s = str(value).strip().lower()
    if not s:
        return None
    m = re.match(r"^(\d{1,3}):(\d{1,2})$", s)  # '1:15' = 1 h 15 min
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(min|minutes|mins)?\.?$", s)
    if m:
        return int(round(float(m.group(1))))
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(hr|hrs|hour|hours|h)\b", s)
    if m:
        return int(round(float(m.group(1)) * 60))
    return None


# ---------- file reading ----------

def _read_sheet(name: str, data: bytes) -> list[list]:
    """Rows (list of raw cell values) from .xlsx or .csv."""
    if name.lower().endswith(".xlsx"):
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        ws = wb.worksheets[0]
        rows = [[c for c in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
        return rows
    text = data.decode("utf-8-sig")
    sample = text[:2048]
    delim = ";" if sample.count(";") > sample.count(",") else ","
    return list(csv.reader(io.StringIO(text), delimiter=delim))


def _is_blank_row(row: list) -> bool:
    return all(c is None or str(c).strip() == "" for c in row)


def _cell_str(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def find_header(rows: list[list]) -> int:
    """First row among the first 10 with >= 3 non-empty cells, followed by a non-empty row."""
    for i, row in enumerate(rows[:10]):
        if _is_blank_row(row):
            continue
        non_empty = sum(1 for c in row if c is not None and str(c).strip())
        nxt = rows[i + 1] if i + 1 < len(rows) else []
        if non_empty >= 3 and not _is_blank_row(nxt):
            return i
    return -1


# ---------- Step A: analyse ----------

def analyse(tenant_id: str, file_name: str, data: bytes) -> dict:
    """Parse the file and suggest a mapping. Raises ValueError for user errors."""
    s = get_settings()
    if len(data) > s.max_log_mb * 1024 * 1024:
        raise ValueError(f"File is larger than {s.max_log_mb} MB.")
    rows = _read_sheet(file_name, data)
    if not rows:
        raise ValueError("The file is empty.")

    header_idx = find_header(rows)
    if header_idx < 0:
        raise ValueError("Could not find a header row (need a row with 3+ columns followed by data).")
    columns = [_cell_str(c) for c in rows[header_idx]]
    # column names must be non-empty and unique
    fixed: list[str] = []
    for i, c in enumerate(columns):
        if not c:
            c = f"Column {i + 1}"
        base, n = c, 2
        while c in fixed:
            c = f"{base} ({n})"
            n += 1
        fixed.append(c)

    data_rows = [r for r in rows[header_idx + 1 :] if not _is_blank_row(r)]
    if not data_rows:
        raise ValueError("No data rows found under the header row.")
    if len(data_rows) > s.max_log_rows:
        raise ValueError(f"File has more than {s.max_log_rows} data rows.")

    def sample_dict(row: list) -> dict:
        out = {}
        for i, col in enumerate(fixed):
            v = row[i] if i < len(row) else None
            if isinstance(v, (dt.datetime, dt.date)):
                v = v.isoformat()
            elif v is not None and not isinstance(v, (int, float)):
                v = str(v).strip()
            out[col] = v
        return out

    sample_rows = [sample_dict(r) for r in data_rows[:5]]
    mapping, source = suggest_mapping(fixed, sample_rows)
    return {
        "file_name": file_name,
        "file_hash": hashlib.sha256(data).hexdigest(),
        "header_row": header_idx + 1,  # 1-based Excel row number
        "columns": fixed,
        "sample_rows": sample_rows,
        "total_rows": len(data_rows),
        "suggested_mapping": mapping,
        "mapping_source": source,
        "rows": data_rows,  # for the caller; not stored in `detected`
    }


# ---------- Step B: import ----------

def import_rows(import_id: str, tenant_id: str, mapping: dict, job_id: str | None = None) -> None:
    s = get_settings()

    def progress(pct: int) -> None:
        if job_id:
            jobs.update(job_id, progress=pct)

    with db() as conn:
        row = conn.execute(
            "select file_path, file_name, column_mapping from log_imports where id = %s and tenant_id = %s",
            (import_id, tenant_id),
        ).fetchone()
    if not row:
        _finish_import(import_id, "failed", error="import not found")
        return
    file_path, file_name, stored_mapping = row
    mapping = {f: mapping.get(f) for f in ("machine_code", "date", "fault", "action", "downtime_min", "technician")}

    try:
        data = storage.download(file_path)
        parsed = analyse(tenant_id, file_name or "upload", data)
    except ValueError as e:
        _finish_import(import_id, "failed", error=str(e))
        return
    except Exception:
        logger.exception("import %s: file unreadable", import_id)
        _finish_import(import_id, "failed", error="Could not read the uploaded file.")
        return

    header_idx = parsed["header_row"] - 1
    columns = parsed["columns"]
    all_rows = _read_sheet(file_name or "upload.xlsx", data)
    idx = {col: i for i, col in enumerate(columns)}

    # tenant machine map: normalised code → (machine_id, model_id, code, name, model, type)
    with db() as conn:
        machines = conn.execute(
            """select m.id, m.model_id, m.code, m.name, mm.model, mm.type
               from machines m left join machine_models mm on mm.id = m.model_id
               where m.tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
    machine_map = {normalise_code(m[2]): m for m in machines}

    # Same file re-imported (force=true): replace the rows of earlier imports with
    # this file's hash, so history never doubles. Their chunks go too.
    with db() as conn:
        frow = conn.execute("select file_hash from log_imports where id = %s", (import_id,)).fetchone()
    if frow and frow[0]:
        with db() as conn:
            old = conn.execute(
                """select l.id from maintenance_logs l
                   join log_imports i on i.id = l.import_id
                   where l.tenant_id = %s and i.file_hash = %s and i.id <> %s""",
                (tenant_id, frow[0], import_id),
            ).fetchall()
            for (old_log_id,) in old:
                conn.execute("delete from chunks where source_type = 'log' and source_id = %s", (old_log_id,))
                conn.execute("delete from maintenance_logs where id = %s", (old_log_id,))
            if old:
                logger.info("import %s: replaced %d rows from earlier imports of the same file", import_id, len(old))

    rows_ok = 0
    rows_skipped = 0
    skipped: list[dict] = []
    pending: list[dict] = []  # rows to insert + chunk metadata

    for r_no, raw_row in enumerate(all_rows[header_idx + 1 :], start=header_idx + 2):
        if _is_blank_row(raw_row):
            continue  # fully blank: ignored, not counted
        cells = {col: (raw_row[idx[col]] if idx[col] < len(raw_row) else None) for col in columns}

        # machine
        mraw = _cell_str(cells[mapping["machine_code"]]) if mapping["machine_code"] else ""
        machine = machine_map.get(normalise_code(mraw)) if mraw else None
        if not mraw:
            rows_skipped += 1
            skipped.append({"row": r_no, "reason": "no machine"})
            continue
        if machine is None:
            rows_skipped += 1
            skipped.append({"row": r_no, "reason": f'unknown machine "{mraw}"'})
            continue

        # fault (required)
        fault = _cell_str(cells[mapping["fault"]]) if mapping["fault"] else ""
        if not fault:
            rows_skipped += 1
            skipped.append({"row": r_no, "reason": "no fault / problem"})
            continue

        date_iso = parse_date(cells[mapping["date"]]) if mapping["date"] else None
        action = _cell_str(cells[mapping["action"]]) if mapping["action"] else ""
        downtime = parse_downtime(cells[mapping["downtime_min"]]) if mapping["downtime_min"] else None
        technician = _cell_str(cells[mapping["technician"]]) if mapping["technician"] else ""

        raw = {}
        for col, v in cells.items():
            if isinstance(v, (dt.datetime, dt.date)):
                v = v.isoformat()
            elif v is not None and not isinstance(v, (int, float)):
                v = str(v).strip()
            raw[col] = v
        # only mapped-field values stay in raw plus every other column (spec: others in raw only)
        pending.append(
            {
                "excel_row": r_no,
                "machine": machine,
                "date": date_iso,
                "fault": fault,
                "action": action,
                "downtime": downtime,
                "technician": technician,
                "raw": raw,
            }
        )
        rows_ok += 1

    # insert rows first (collect ids + chunk texts), then embed in batches
    inserts: list[tuple[dict, str, str]] = []  # (pending, log_id, chunk_text)
    with db() as conn:
        conn.execute("update log_imports set status = 'importing' where id = %s", (import_id,))
    for p in pending:
        machine = p["machine"]
        machine_id, model_id, code, _name, model, mtype = machine
        model_label = " ".join(x for x in [model, mtype] if x)
        parts = [f"Breakdown on {code}" + (f" ({model_label})" if model_label else "")]
        if p["date"]:
            d = dt.date.fromisoformat(p["date"])
            parts.append(f"on {d.strftime('%d-%m-%Y')}")
        text = " ".join(parts) + "."
        text += f" Problem: {p['fault']}"
        if p["action"]:
            text += f". Action: {p['action']}"
        if p["downtime"]:
            text += f". Downtime: {p['downtime']} min"
        if p["technician"]:
            text += f". Attended by: {p['technician']}"
        remarks = p["raw"].get("Remarks") or ""
        if remarks:
            text += f". Remarks: {remarks}"
        with db() as conn:
            cur = conn.execute(
                """insert into maintenance_logs
                   (tenant_id, machine_id, import_id, date, fault, action, downtime_min, technician, raw)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   returning id""",
                (
                    tenant_id,
                    machine_id,
                    import_id,
                    p["date"],
                    p["fault"],
                    p["action"] or None,
                    p["downtime"],
                    p["technician"] or None,
                    json.dumps(p["raw"], ensure_ascii=False),
                ),
            )
            log_id = str(cur.fetchone()[0])
        inserts.append((p, log_id, text))

    total = max(len(inserts), 1)
    vectors = embeddings.embed_passages([t for _, _, t in inserts]) if inserts else []
    for done, ((p, log_id, text), vec) in enumerate(zip(inserts, vectors, strict=True)):
        machine_id, model_id = p["machine"][0], p["machine"][1]
        meta = json.dumps({"row": p["excel_row"], "embed_model": s.embed_model})
        with db() as conn:
            conn.execute(
                """insert into chunks
                   (tenant_id, source_type, source_id, model_id, machine_id, text, embedding, chunk_index, meta)
                   values (%s, 'log', %s, %s, %s, %s, %s, 0, %s)""",
                (tenant_id, log_id, model_id, machine_id, text, list(map(float, vec)), meta),
            )
        if job_id:
            progress(50 + int(45 * (done + 1) / total))

    _finish_import(
        import_id,
        "done",
        rows_ok=rows_ok,
        rows_skipped=rows_skipped,
        skipped=skipped,
        mapping=mapping,
    )
    logger.info(
        "import %s: %s imported, %s skipped",
        import_id,
        rows_ok,
        rows_skipped,
    )


def _finish_import(
    import_id: str,
    status: str,
    rows_ok: int | None = None,
    rows_skipped: int | None = None,
    skipped: list[dict] | None = None,
    mapping: dict | None = None,
    error: str | None = None,
) -> None:
    detected_update: dict = {}
    if skipped is not None:
        detected_update["skipped"] = skipped[:100]
    if error is not None:
        detected_update["error"] = error
    with db() as conn:
        if detected_update:
            conn.execute(
                "update log_imports set detected = coalesce(detected, '{}'::jsonb) || %s::jsonb where id = %s",
                (json.dumps(detected_update), import_id),
            )
        if mapping is not None:
            conn.execute(
                "update log_imports set column_mapping = %s::jsonb where id = %s",
                (json.dumps(mapping), import_id),
            )
        conn.execute(
            "update log_imports set status = %s, rows_ok = coalesce(%s, rows_ok), "
            "rows_skipped = coalesce(%s, rows_skipped) where id = %s",
            (status, rows_ok, rows_skipped, import_id),
        )
