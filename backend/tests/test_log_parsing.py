"""Unit tests for breakdown-log parsing (no DB, no files)."""

import datetime as dt

from app.services.log_import import find_header, normalise_code, parse_date, parse_downtime

# ===== machine codes =====

def test_normalise_code_variants() -> None:
    assert normalise_code("HP-07") == "HP7"
    assert normalise_code("HP 07") == "HP7"
    assert normalise_code("hp7") == "HP7"
    assert normalise_code("HP-007") == "HP7"
    assert normalise_code("CNC 3") == "CNC3"
    assert normalise_code("AC-01") == "AC1"
    assert normalise_code("") == ""


# ===== dates (day-first) =====

def test_parse_date_day_first() -> None:
    assert parse_date("05/03/2026") == "2026-03-05"  # 5 March, not 3 May
    assert parse_date("05/03/26") == "2026-03-05"
    assert parse_date("31-01-2026") == "2026-01-31"


def test_parse_date_passthrough_and_garbage() -> None:
    assert parse_date(dt.date(2026, 3, 5)) == "2026-03-05"
    assert parse_date(dt.datetime(2026, 3, 5, 10, 30)) == "2026-03-05"
    assert parse_date("not a date") is None
    assert parse_date("") is None
    assert parse_date(None) is None


# ===== downtime =====

def test_parse_downtime() -> None:
    assert parse_downtime(40) == 40
    assert parse_downtime("45 min") == 45
    assert parse_downtime("1.5 hr") == 90
    assert parse_downtime("2 hours") == 120
    assert parse_downtime("1:15") == 75
    assert parse_downtime("abc") is None
    assert parse_downtime("") is None
    assert parse_downtime(None) is None


# ===== header detection =====

def test_find_header_skips_title_rows() -> None:
    rows = [
        ["Shree Hydraulics", None, None, None],
        ["Breakdown Log 2026", None, None, None],
        ["Date", "M/C No", "Problem", "Action Taken"],
        ["05/03/2026", "HP-07", "Noise", "Changed bearings"],
    ]
    assert find_header(rows) == 2


def test_find_header_no_header() -> None:
    assert find_header([["just", "data"], ["no", "header"]]) == -1
