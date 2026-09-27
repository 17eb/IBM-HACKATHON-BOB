from core import parity
from core.records import INPUT_FIELDS, OUTPUT_FIELDS, TRAILER_FIELDS, parse, split_records, to_decimal

GOLDEN = (
    b"C0000001OK 000075520000003770000079290\n"
    b"C0000002ERR00000000000000000000000000\n"
    b"TRL0000020000010000000000792\n"
)


def test_layout_widths_are_contiguous():
    for fields, total in ((INPUT_FIELDS, 28), (OUTPUT_FIELDS, 37), (TRAILER_FIELDS, 28)):
        pos = 1
        for f in fields:
            assert f.start == pos, f.name
            pos += f.width
        assert pos - 1 == total


def test_parse_input_record():
    rec = parse(b"C000012300125000000725060017", INPUT_FIELDS)
    assert rec["PRINCIPAL"] == "001250000"
    assert rec["DAYS-LATE"] == "017"
    assert str(to_decimal("00725", 4)) == "0.0725"
    assert to_decimal("0012A0000", 2) is None


def test_split_records_preserves_bytes():
    assert split_records(b"a \nb\n") == [b"a ", b"b"]
    assert split_records(b"a \r\nb\r\n") == [b"a ", b"b"]
    assert split_records(b"a\r") == [b"a\r"]
    assert split_records(b"") == []


def test_identical_outputs_pass():
    report = parity.compare(GOLDEN, GOLDEN)
    assert report["status"] == "pass"
    assert report["records_matched"] == 2 and report["trailer_match"]


def test_one_cent_difference_fails_with_field_and_rule():
    candidate = GOLDEN.replace(b"000075520", b"000075530")
    report = parity.compare(GOLDEN, candidate)
    assert report["status"] == "fail"
    m = report["mismatches"][0]
    assert (m["record_no"], m["cust_id"], m["field"], m["rule_id"]) == (1, "C0000001", "MONTHLY-INT", "R1")
    assert (m["expected"], m["actual"]) == ("000075520", "000075530")


def test_late_fee_rule_depends_on_days_late():
    inputs = b"C000000100125000000725060075\nC000000200000000000725060017\n"
    candidate = GOLDEN.replace(b"00000377", b"00000378")
    report = parity.compare(GOLDEN, candidate, inputs)
    assert report["mismatches"][0]["rule_id"] == "R3"
    report = parity.compare(GOLDEN, candidate, inputs.replace(b"060075", b"060030"))
    assert report["mismatches"][0]["rule_id"] == "R2"


def test_trailer_mismatch_is_reported():
    candidate = GOLDEN.replace(b"TRL000002000001", b"TRL000002000000")
    report = parity.compare(GOLDEN, candidate)
    assert report["status"] == "fail" and not report["trailer_match"]
    assert report["mismatches"][0]["field"] == "ERR-COUNT"


def test_missing_record_is_reported():
    lines = GOLDEN.split(b"\n")
    candidate = b"\n".join([lines[0], lines[2]]) + b"\n"
    report = parity.compare(GOLDEN, candidate)
    assert report["status"] == "fail"
    assert report["records_actual"] == 1
    assert any(m["field"] == "<RECORD>" for m in report["mismatches"])


def test_trailing_space_difference_is_not_ignored():
    candidate = GOLDEN.replace(b"C0000001OK 000075520000003770000079290\n",
                               b"C0000001OK 000075520000003770000079290 \n")
    report = parity.compare(GOLDEN, candidate)
    assert report["status"] == "fail"
    assert report["mismatches"][0]["field"] == "<RECORD-LENGTH>"
