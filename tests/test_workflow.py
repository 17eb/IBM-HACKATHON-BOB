import pytest

from core import workflow
from tests.conftest import needs_cobc, needs_java

DATASETS = ["ds01_normal", "ds02_edges", "ds03_mixed_errors"]


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


@needs_java
def test_naive_java_is_caught(workspace):
    report = workflow.compare_parity("ds02_edges", "java-naive", root=workspace)
    assert report["status"] == "fail"
    assert {"R1", "R2"} <= set(report["mismatches_by_rule"])
    stored = workflow.get_run_report(report["run_id"], workspace)
    assert stored["mismatch_count"] == report["mismatch_count"]
