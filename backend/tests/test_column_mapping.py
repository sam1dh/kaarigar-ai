"""Unit tests for the rules-based Excel column mapping (no LLM, no DB)."""

from app.services.column_mapping import FIELDS, rules_mapping


def test_demo_columns_map_to_all_fields() -> None:
    columns = ["Date", "M/C No", "Problem", "Action Taken", "Down Time (min)", "Attended By"]
    mapping = rules_mapping(columns)
    assert mapping["date"] == "Date"
    assert mapping["machine_code"] == "M/C No"
    assert mapping["fault"] == "Problem"
    assert mapping["action"] == "Action Taken"
    assert mapping["downtime_min"] == "Down Time (min)"
    assert mapping["technician"] == "Attended By"


def test_each_column_used_at_most_once() -> None:
    # 'Machine Date' contains keywords of both fields; date wins field order first,
    # so machine_code must fall back to 'Machine'.
    columns = ["Machine Date", "Machine", "Problem"]
    mapping = rules_mapping(columns)
    used = [v for v in mapping.values() if v]
    assert len(used) == len(set(used))


def test_unknown_columns_map_to_none() -> None:
    mapping = rules_mapping(["Random", "Stuff"])
    assert all(mapping[f] is None for f in FIELDS)


def test_case_insensitive_and_hindi() -> None:
    mapping = rules_mapping(["तारीख", "मशीन", "समस्या"])
    assert mapping["date"] == "तारीख"
    assert mapping["machine_code"] == "मशीन"
    assert mapping["fault"] == "समस्या"
