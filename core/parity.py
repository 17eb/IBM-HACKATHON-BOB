"""Exact field-level parity between a COBOL golden and a candidate output.

No trimming, no numeric tolerance: every field must match byte for byte.
"""

from __future__ import annotations

from collections import Counter

from core.programs import Program
from core.records import (
    OUTPUT_FIELDS,
    TRAILER_FIELDS,
    TRAILER_TAG,
    days_late,
    field_text,
    split_records,
)

MAX_LISTED_MISMATCHES = 500


def _split_trailer(records: list[bytes], prefix: bytes | None) -> tuple[list[bytes], bytes | None]:
    if prefix is not None and records and records[-1].startswith(prefix):
        return records[:-1], records[-1]
    return records, None


def _rule_for(field_name: str, base_rule: str | None, input_record: bytes | None,
              program: Program | None) -> str | None:
    if program is not None:
        for override in program.rule_overrides:
            if override.output_field != field_name or input_record is None:
                continue
            raw = field_text(input_record, override.input_field)
            if not raw or not raw.isascii() or not raw.isdigit():
                continue
            value = int(raw)
            threshold = override.value
            matches = {
                "gt": value > threshold, "ge": value >= threshold, "eq": value == threshold,
                "le": value <= threshold, "lt": value < threshold,
            }
            if matches[override.operator]:
                return override.rule_id
        return base_rule
    if field_name == "LATE-FEE":
        days = days_late(input_record)
        return "R3" if days is not None and days > 60 else "R2"
    return base_rule


def _text(record: bytes | None) -> str | None:
    return None if record is None else record.decode("latin-1")


def compare(golden: bytes, candidate: bytes, input_data: bytes | None = None,
            program: Program | None = None) -> dict:
    """Compare fixed-width outputs using a program definition (LOANCALC by default)."""
    detail_fields = program.detail_fields if program else OUTPUT_FIELDS
    trailer_fields = program.trailer_fields if program else TRAILER_FIELDS
    identifier = program.identifier_field if program else OUTPUT_FIELDS[0]
    prefix = program.trailer_prefix if program else TRAILER_TAG
    g_details, g_trailer = _split_trailer(split_records(golden), prefix)
    c_details, c_trailer = _split_trailer(split_records(candidate), prefix)
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
                "cust_id": field_text(present, identifier),
                "field": "<RECORD>",
                "expected": _text(expected),
                "actual": _text(actual),
                "rule_id": "R5",
                "detail": "missing record" if actual is None else "unexpected extra record",
            })
            continue
        before = len(mismatches)
        for f in detail_fields:
            exp, act = field_text(expected, f), field_text(actual, f)
            if exp != act:
                mismatches.append({
                    "record_no": record_no,
                    "cust_id": field_text(expected, identifier),
                    "field": f.name,
                    "expected": exp,
                    "actual": act,
                    "rule_id": _rule_for(f.name, f.rule, input_record, program),
                })
        if len(mismatches) == before:  # all fields equal but bytes differ (length / trailing bytes)
            mismatches.append({
                "record_no": record_no,
                "cust_id": field_text(expected, identifier),
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
        for f in trailer_fields:
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
