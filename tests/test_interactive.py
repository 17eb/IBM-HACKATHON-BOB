import hashlib
import json
import subprocess

from core import interactive
from tests.conftest import needs_java


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _case(tmp_path):
    source = tmp_path / "ATM.cbl"
    source.write_bytes(b">>SOURCE FORMAT FREE\nprogram-id. atm.\n")
    case_dir = interactive._case_dir(tmp_path, source, "balance")
    case_dir.mkdir(parents=True)
    stdin = b"1234\n"
    golden = b"PIN?OK:1234\n"
    (case_dir / "stdin.txt").write_bytes(stdin)
    (case_dir / "golden.stdout").write_bytes(golden)
    manifest = {
        "schema": interactive.SCHEMA, "case_id": "balance", "origin": "local_gnucobol",
        "source": {"path": "ATM.cbl", "sha256": _sha(source.read_bytes())},
        "stdin": {"path": interactive._rel(tmp_path, case_dir / "stdin.txt"), "sha256": _sha(stdin)},
        "golden": {"path": interactive._rel(tmp_path, case_dir / "golden.stdout"), "sha256": _sha(golden)},
    }
    (case_dir / "manifest.json").write_text(json.dumps(manifest))
    java_dir = tmp_path / "java"
    java_dir.mkdir()
    java = java_dir / "ATM.java"
    java.write_text("public class ATM { public static void main(String[] a) { "
                    "String pin = new java.util.Scanner(System.in).nextLine(); "
                    "System.out.print(\"PIN?OK:\" + pin + \"\\n\"); }}")
    return source, case_dir, java


def test_cases_are_scoped_to_source_path(tmp_path):
    left = tmp_path / "one" / "PROGRAM.cbl"
    right = tmp_path / "two" / "PROGRAM.cbl"
    left.parent.mkdir()
    right.parent.mkdir()
    left.write_text("program-id. one.")
    right.write_text("program-id. two.")
    assert interactive._case_dir(tmp_path, left, "case1") != interactive._case_dir(
        tmp_path, right, "case1")


def test_generic_capture_freezes_input_and_records_compiler_format(tmp_path, monkeypatch):
    (tmp_path / "PAYROLL.cob").write_text("program-id. payroll.\n")
    calls = []

    def fake_run(args, root, *, stdin=None, step):
        calls.append((args, stdin, step))
        output = (b"GnuCOBOL 3.2\n" if step == "cobc --version" else
                  b"RESULT:" + stdin if step == "run COBOL" else b"")
        return subprocess.CompletedProcess(args, 0, output, b"")

    monkeypatch.setattr(interactive, "_run", fake_run)
    captured = interactive.capture_golden("PAYROLL.cob", "case1", "A\n", tmp_path,
                                          source_format="free")
    assert captured["status"] == "captured"
    assert any("-free" in args for args, _, step in calls if step == "compile COBOL")
    assert interactive.capture_golden("PAYROLL.cob", "case1", "A\n", tmp_path)["status"] == "frozen"
    changed = interactive.capture_golden("PAYROLL.cob", "case1", "B\n", tmp_path)
    assert changed["status"] == "error"
    assert "different stdin" in changed["errors"][0]["message"]


@needs_java
def test_interactive_java_exact_transcript_and_detects_mismatch(tmp_path):
    _, case_dir, java = _case(tmp_path)
    passed = interactive.verify_java("ATM.cbl", "balance", "java", "ATM", tmp_path)
    assert passed["status"] == "pass"
    assert passed["first_difference_byte"] is None

    java.write_text(java.read_text().replace("PIN?OK:", "PIN?NO:"))
    failed = interactive.verify_java("ATM.cbl", "balance", "java", "ATM", tmp_path)
    assert failed["status"] == "fail"
    assert isinstance(failed["first_difference_byte"], int)
    assert (case_dir / "golden.stdout").read_bytes() == b"PIN?OK:1234\n"


@needs_java
def test_interactive_manifest_hash_rejected_before_java(tmp_path):
    source, case_dir, _ = _case(tmp_path)
    (case_dir / "golden.stdout").write_bytes(b"tampered")
    result = interactive.verify_java("ATM.cbl", "balance", "java", "ATM", tmp_path)
    assert result["status"] == "error"
    assert "golden sha256 mismatch" in result["errors"][0]["message"]

    (case_dir / "golden.stdout").write_bytes(b"PIN?OK:1234\n")
    source.write_bytes(source.read_bytes() + b"* changed\n")
    result = interactive.verify_java("ATM.cbl", "balance", "java", "ATM", tmp_path)
    assert result["status"] == "error"
    assert "source sha256 mismatch" in result["errors"][0]["message"]
