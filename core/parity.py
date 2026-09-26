"""Exact field-level parity between a COBOL golden and a candidate output.

No trimming, no numeric tolerance: every field must match byte for byte.
"""

from __future__ import annotations

from collections import Counter

from core.records import (
    OUTPUT_FIELDS,
    TRAILER_FIELDS,
    TRAILER_TAG,
    days_late,
    field_text,
    split_records,
)

MAX_LISTED_MISMATCHES = 500


def _split_trailer(records: list[bytes]) -> tuple[list[bytes], bytes | None]:
    if records and records[-1].startswith(TRAILER_TAG):
        return records[:-1], records[-1]
    return records, None


def _rule_for(field_name: str, base_rule: str | None, input_record: bytes | None) -> str | None:
    if field_name == "LATE-FEE":
        days = days_late(input_record)
        return "R3" if days is not None and days > 60 else "R2"
    return base_rule


def _text(record: bytes | None) -> str | None:
    return None if record is None else record.decode("latin-1")


def compare(golden: bytes, candidate: bytes, input_data: bytes | None = None) -> dict:
    """Compare two LOANCALC outputs. Returns a report dict with status 'pass' or 'fail'."""
    g_details, g_trailer = _split_trailer(split_records(golden))
    c_details, c_trailer = _split_trailer(split_records(candidate))
    inputs = split_records(input_data) if input_data is not None else []

    mismatches: list[dict] = []
    matched = 0
    for i in range(max(len(g_details), len(c_details))):
        expected = g_details[i] if i < len(g_details) else None
        actual = c_details[i] if i < len(c_details) else None
        input_record = inputs[i] if i < len(inputs) else None
        record_no = i + 1
        if expected == actual:
            matched += 1
            continue
        if expected is None or actual is None:
            present = expected if expected is not None else actual
            mismatches.append({
                "record_no": record_no,
                "cust_id": field_text(present, OUTPUT_FIELDS[0]),
                "field": "<RECORD>",
                "expected": _text(expected),
                "actual": _text(actual),
                "rule_id": "R5",
                "detail": "missing record" if actual is None else "unexpected extra record",
            })
            continue
        before = len(mismatches)
        for f in OUTPUT_FIELDS:
            exp, act = field_text(expected, f), field_text(actual, f)
            if exp != act:
                mismatches.append({
                    "record_no": record_no,
                    "cust_id": field_text(expected, OUTPUT_FIELDS[0]),
                    "field": f.name,
                    "expected": exp,
                    "actual": act,
                    "rule_id": _rule_for(f.name, f.rule, input_record),
                })
        if len(mismatches) == before:  # all fields equal but bytes differ (length / trailing bytes)
            mismatches.append({
                "record_no": record_no,
                "cust_id": field_text(expected, OUTPUT_FIELDS[0]),
                "field": "<RECORD-LENGTH>",
                "expected": _text(expected),
                "actual": _text(actual),
                "rule_id": "LAYOUT",
            })

    trailer_mismatches: list[dict] = []
    if g_trailer is None or c_trailer is None:
        if g_trailer != c_trailer:
            trailer_mismatches.append({
                "record_no": "TRAILER", "cust_id": None, "field": "<TRAILER>",
                "expected": _text(g_trailer), "actual": _text(c_trailer), "rule_id": "R5",
            })
    elif g_trailer != c_trailer:
        for f in TRAILER_FIELDS:
            exp, act = field_text(g_trailer, f), field_text(c_trailer, f)
            if exp != act:
                trailer_mismatches.append({
                    "record_no": "TRAILER", "cust_id": None, "field": f.name,
                    "expected": exp, "actual": act, "rule_id": f.rule,
                })
        if not trailer_mismatches:
            trailer_mismatches.append({
                "record_no": "TRAILER", "cust_id": None, "field": "<RECORD-LENGTH>",
                "expected": _text(g_trailer), "actual": _text(c_trailer), "rule_id": "LAYOUT",
            })

    all_mismatches = mismatches + trailer_mismatches
    by_field = Counter(m["field"] for m in all_mismatches)
    by_rule = Counter(m["rule_id"] for m in all_mismatches)
    failed_records = len({m["record_no"] for m in mismatches})
    return {
        "status": "pass" if not all_mismatches else "fail",
        "records_expected": len(g_details),
        "records_actual": len(c_details),
        "records_matched": matched,
        "records_mismatched": failed_records,
        "trailer_match": not trailer_mismatches,
        "mismatch_count": len(all_mismatches),
        "mismatches_by_field": dict(by_field),
        "mismatches_by_rule": dict(by_rule),
        "mismatches": all_mismatches[:MAX_LISTED_MISMATCHES],
        "mismatches_truncated": len(all_mismatches) > MAX_LISTED_MISMATCHES,
    }
