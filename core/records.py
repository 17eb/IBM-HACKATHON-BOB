"""LOANCALC record layouts (docs/record_layouts.md) and byte-preserving record helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Field:
    name: str
    start: int  # 1-based column
    width: int
    scale: int | None = None  # implied decimals; None for alphanumeric
    rule: str | None = None

    @property
    def slice(self) -> slice:
        return slice(self.start - 1, self.start - 1 + self.width)


INPUT_FIELDS = (
    Field("CUST-ID", 1, 8),
    Field("PRINCIPAL", 9, 9, 2),
    Field("ANNUAL-RATE", 18, 5, 4),
    Field("TERM-MONTHS", 23, 3, 0),
    Field("DAYS-LATE", 26, 3, 0),
)
OUTPUT_FIELDS = (
    Field("CUST-ID", 1, 8, rule="LAYOUT"),
    Field("STATUS", 9, 3, rule="R4"),
    Field("MONTHLY-INT", 12, 9, 2, rule="R1"),
    Field("LATE-FEE", 21, 8, 2, rule="R2"),
    Field("TOTAL-DUE", 29, 9, 2, rule="R1+R2"),
)
TRAILER_FIELDS = (
    Field("TRL-ID", 1, 3, rule="R5"),
    Field("REC-COUNT", 4, 6, 0, rule="R5"),
    Field("ERR-COUNT", 10, 6, 0, rule="R5"),
    Field("TOTAL-DUE-SUM", 16, 13, 2, rule="R5"),
)
INPUT_LEN, OUTPUT_LEN, TRAILER_LEN = 28, 37, 28
TRAILER_TAG = b"TRL"


def split_records(data: bytes) -> list[bytes]:
    """Split LF or CRLF records without trimming any field bytes."""
    if not data:
        return []
    records = data.split(b"\n")
    ended_with_lf = records[-1] == b""
    if ended_with_lf:
        records.pop()
    return [
        rec[:-1] if rec.endswith(b"\r") and (i < len(records) - 1 or ended_with_lf) else rec
        for i, rec in enumerate(records)
    ]


def field_bytes(record: bytes, field: Field) -> bytes:
    return record[field.slice]


def field_text(record: bytes, field: Field) -> str:
    return field_bytes(record, field).decode("latin-1")


def parse(record: bytes, fields: tuple[Field, ...]) -> dict[str, str]:
    return {f.name: field_text(record, f) for f in fields}


def to_decimal(text: str, scale: int) -> Decimal | None:
    """Display value of an unsigned implied-decimal field, or None if not numeric."""
    if not text.isdigit():
        return None
    return Decimal(int(text)).scaleb(-scale)


def days_late(input_record: bytes | None) -> int | None:
    if input_record is None:
        return None
    text = field_text(input_record, INPUT_FIELDS[4])
    return int(text) if text.isdigit() else None
