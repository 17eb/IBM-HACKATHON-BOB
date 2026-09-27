import pytest

from core import workflow
from tests.conftest import needs_cobc, needs_java
from tools import verify_all

DATASETS = ["ds01_normal", "ds02_edges", "ds03_mixed_errors"]


def test_prepare_java_port_describes_source_target_and_fixtures(workspace):
    brief = workflow.prepare_java_port(root=workspace)
    assert brief["status"] == "ok"
    assert brief["source_path"] == "legacy/LOANCALC.cbl"
    assert brief["java_main_class"] == "com.cobolbridge.LoanCalc"
    assert brief["all_goldens_ready"]
    assert {item["dataset_id"] for item in brief["datasets"]} == set(DATASETS)


def test_prepare_java_port_reports_missing_golden(workspace):
    (workspace / "data" / "golden" / "ds01_normal.out").unlink()
    brief = workflow.prepare_java_port(root=workspace)
    assert brief["status"] == "ok" and not brief["all_goldens_ready"]
    assert brief["datasets"][0]["golden_path"] is None


def test_tampered_golden_is_rejected_before_running_java(workspace):
    golden = workspace / "data" / "golden" / "ds01_normal.out"
    raw = golden.read_bytes()
    golden.write_bytes(b"X" + raw[1:])
    report = workflow.compare_parity("ds01_normal", root=workspace)
    assert report["status"] == "error"
    assert "golden sha256 mismatch" in report["errors"][0]["message"]
    assert not (workspace / "runs").exists()
    brief = workflow.prepare_java_port(root=workspace)
    assert not brief["all_goldens_ready"]
    assert not brief["datasets"][0]["fixture_valid"]


def test_cli_fails_for_tampered_golden(workspace, capsys):
    golden = workspace / "data" / "golden" / "ds01_normal.out"
    raw = golden.read_bytes()
    golden.write_bytes(b"X" + raw[1:])
    assert verify_all.main(["--candidate", "java"]) == 1
    assert "golden sha256 mismatch" in capsys.readouterr().out


def test_missing_manifest_is_rejected_before_running_java(workspace):
    (workspace / "data" / "manifests" / "ds01_normal.json").unlink()
    report = workflow.compare_parity("ds01_normal", root=workspace)
    assert report["status"] == "error"
    assert "no manifest" in report["errors"][0]["message"]
    assert not (workspace / "runs").exists()


def test_changed_source_is_rejected_before_running_java(workspace):
    source = workspace / "legacy" / "LOANCALC.cbl"
    source.write_bytes(source.read_bytes() + b"\n")
    report = workflow.compare_parity("ds01_normal", root=workspace)
    assert report["status"] == "error"
    assert "source sha256 mismatch" in report["errors"][0]["message"]


def test_manifest_cannot_redirect_golden_path(workspace):
    import json

    path = workspace / "data" / "manifests" / "ds01_normal.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["golden"]["path"] = "data/golden/ds02_edges.out"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    report = workflow.compare_parity("ds01_normal", root=workspace)
    assert report["status"] == "error"
    assert "golden path must be" in report["errors"][0]["message"]


@needs_java
def test_verify_java_port_requires_every_dataset_and_trailer(workspace):
    result = workflow.verify_java_port(root=workspace)
    assert result["status"] == "pass"
    assert result["datasets_total"] == result["datasets_passed"] == 3
    assert result["mismatch_count"] == 0
    assert all(item["trailer_match"] for item in result["results"])
    assert all((workspace / "data" / "manifests" / f"{item['dataset_id']}.json").exists()
               for item in result["results"])


@needs_java
def test_verify_java_port_fails_on_missing_golden(workspace):
    (workspace / "data" / "golden" / "ds01_normal.out").unlink()
    result = workflow.verify_java_port(root=workspace)
    assert result["status"] == "fail" and result["datasets_passed"] == 2
    assert result["results"][0]["status"] == "error"


def test_inspect_cobol_finds_paragraphs_and_rules(workspace):
    result = workflow.inspect_cobol("legacy/LOANCALC.cbl", workspace)
    assert result["status"] == "ok" and result["heuristic"] is True
    names = {p["name"] for p in result["paragraphs"]}
    assert {"CALC-INTEREST", "CALC-LATE-FEE", "VALIDATE-RECORD", "WRITE-TRAILER"} <= names
    rounded = {c["target"]: c["rounded"] for c in result["computations"]}
    assert rounded["WS-INT"] is True and rounded["WS-FEE"] is False
    assert any("truncated" in q for q in result["unresolved_questions"])


def test_inspect_cobol_rejects_traversal(workspace):
    result = workflow.inspect_cobol("../../etc/passwd", workspace)
    assert result["status"] == "error"


def test_inspect_free_format_interactive_cobol(tmp_path):
    (tmp_path / "ATM.cbl").write_text(
        ">>SOURCE FORMAT FREE\n"
        "identification division.\nprogram-id. atm.\n"
        "data division.\nworking-storage section.\n"
        "01 entered-pin pic x(4).\n01 char-index binary-long.\n"
        "procedure division.\nmain.\n"
        "    display 'PIN:' with no advancing\n    accept entered-pin\n"
        "    compute char-index = 1\n    goback.\n",
        encoding="ascii",
    )
    result = workflow.start_cobol_port("ATM.cbl", root=tmp_path)
    source = result["source"]
    assert result["status"] == "ok" and result["registered_programs"] == []
    assert source["source_format"] == "free"
    assert source["io_mode"] == "interactive_stdio"
    assert {item["name"] for item in source["data_items"]} == {"entered-pin", "char-index"}
    assert {item["name"] for item in source["paragraphs"]} == {"main"}
    assert source["interactive_io"]["accept_lines"]
    assert "verify_interactive_java" in result["next_steps"][1]


def test_free_format_can_be_declared_without_source_directive(tmp_path):
    (tmp_path / "program.cob").write_text(
        "identification division.\nprogram-id. demo.\n"
        "data division.\nworking-storage section.\n"
        "01 choice pic x.\nprocedure division.\nmain.\n    accept choice\n")
    result = workflow.start_cobol_port("program.cob", root=tmp_path, source_format="free")
    assert result["source"]["source_format"] == "free"
    assert result["source"]["paragraphs"][0]["name"] == "main"
    assert result["source"]["data_items"][0]["name"] == "choice"


def test_compare_parity_missing_golden(workspace):
    (workspace / "data" / "golden" / "ds01_normal.out").unlink()
    result = workflow.compare_parity("ds01_normal", "java", root=workspace)
    assert result["status"] == "error"
    assert "capture_golden" in result["errors"][0]["message"]


def test_unknown_candidate_is_an_error(workspace):
    result = workflow.run_candidate("ds01_normal", "cobol-on-rails", workspace)
    assert result["status"] == "error"


def test_frozen_golden_is_not_overwritten(workspace):
    golden = workspace / "data" / "golden" / "ds01_normal.out"
    before = golden.read_bytes()
    result = workflow.capture_golden("ds01_normal", root=workspace)
    assert result["status"] == "frozen"
    assert golden.read_bytes() == before


@needs_cobc
def test_capture_golden_reproduces_committed_golden(workspace):
    committed = (workspace / "data" / "golden" / "ds02_edges.out").read_bytes()
    result = workflow.capture_golden("ds02_edges", force_new_version=True, root=workspace)
    assert result["status"] == "captured"
    assert (workspace / "data" / "golden" / "ds02_edges.out").read_bytes() == committed
    assert result["manifest"]["supersedes"]["sha256"] == result["manifest"]["golden"]["sha256"]


@needs_java
@pytest.mark.parametrize("dataset_id", DATASETS)
def test_faithful_java_matches_every_golden(workspace, dataset_id):
    report = workflow.compare_parity(dataset_id, "java", root=workspace)
    assert report["status"] == "pass", report["mismatches"][:3]
    assert report["trailer_match"] and report["mismatch_count"] == 0
    assert len(report["fixture_manifest_sha256"]) == 64


def test_changed_input_line_endings_are_rejected_before_running_java(workspace):
    path = workspace / "data" / "inputs" / "ds02_edges.dat"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    report = workflow.compare_parity("ds02_edges", "java", root=workspace)
    assert report["status"] == "error"
    assert "input sha256 mismatch" in report["errors"][0]["message"]


@needs_java
def test_naive_java_is_caught(workspace):
    report = workflow.compare_parity("ds02_edges", "java-naive", root=workspace)
    assert report["status"] == "fail"
    assert {"R1", "R2"} <= set(report["mismatches_by_rule"])
    stored = workflow.get_run_report(report["run_id"], workspace)
    assert stored["mismatch_count"] == report["mismatch_count"]
