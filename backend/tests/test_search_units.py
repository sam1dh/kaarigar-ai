"""Unit tests for the pure helpers in search/knowledge (no DB)."""

import datetime as dt

from app.services import search
from app.services.knowledge import expand_terms

# ===== code variants =====

def test_code_variants() -> None:
    assert search._code_variants("E05 alarm") == ["E-05", "E05"]
    assert search._code_variants("what does error e-07 mean") == ["E-07", "E07"]
    # lettered+digit tokens are kept whole ("alarm 2001" → ALARM-2001); they simply
    # never match anything via ILIKE, which is harmless
    assert search._code_variants("alarm 2001") == ["ALARM-2001", "ALARM2001"]
    assert search._code_variants("pump thak thak") == []


def test_code_variants_dedupe() -> None:
    assert search._code_variants("E05 E-05") == ["E-05", "E05"]


# ===== friendly rank names =====

def test_friendly_ranks_merges_retriever_pairs() -> None:
    assert search._friendly_ranks({"v": 1, "kc": 2, "kw": 5, "gr": 3}) == {
        "vector": 1,
        "keyword": 2,
        "graph": 3,
    }
    assert search._friendly_ranks({"kw": 4, "gl": 2}) == {"keyword": 4, "graph": 2}
    assert search._friendly_ranks({}) == {}


# ===== titles =====

def _info(stype: str, **over) -> dict:
    base = {
        "source_type": stype,
        "page": 3,
        "doc_title": "HPX-200 Service Manual",
        "machine_code": "HP-07",
        "author": "Ramesh Patil",
        "record_date": dt.datetime(2026, 1, 29, 10, 30),
        "log_date": dt.date(2026, 1, 19),
    }
    base.update(over)
    return base


def test_title_for_manual() -> None:
    assert search._title_for(_info("manual")) == "HPX-200 Service Manual · p.3"


def test_title_for_record() -> None:
    assert search._title_for(_info("record")) == "Repair record · HP-07 · 29 Jan 2026 · Ramesh Patil"


def test_title_for_log() -> None:
    assert search._title_for(_info("log")) == "Breakdown log · HP-07 · 19 Jan 2026"


# ===== glossary expansion =====

def test_expand_terms_appends_meaning() -> None:
    glossary = {"thak-thak": "knocking sound", "awaaz": "noise"}
    qx, used = expand_terms("pump thak thak awaaz", glossary)
    assert qx == "pump thak thak (knocking sound) awaaz (noise)"
    assert used == ["thak-thak", "awaaz"]


def test_expand_terms_case_insensitive_and_spaced() -> None:
    qx, used = expand_terms("Thak Thak noise", {"thak-thak": "knocking sound"})
    assert "knocking sound" in qx
    assert used == ["thak-thak"]


def test_expand_terms_no_match() -> None:
    qx, used = expand_terms("coolant level low", {"thak-thak": "knocking sound"})
    assert qx == "coolant level low"
    assert used == []
