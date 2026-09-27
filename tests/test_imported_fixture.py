"""Synthetic EBCDIC FB fixtures exercise the import boundary without an IBM runtime."""

import hashlib
import json
from pathlib import Path

from core import workflow
from core.records import split_records
from tests.conftest import needs_java
from tools import import_golden as import_cli


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _import_sources(workspace, *, origin="simulated_ibm_style"):
    source = workspace / "legacy" / "LOANCALC.cbl"
    inputs = split_records((workspace / "data" / "inputs" / "ds01_normal.dat").read_bytes())
    outputs = split_records((workspace / "data" / "golden" / "ds01_normal.out").read_bytes())
    folder = workspace / "data" / "import_sources" / "ibm_case"
    folder.mkdir(parents=True)
    raw_input = b"".join(record.decode("ascii").encode("cp037") for record in inputs)
    raw_output = b"".join((record + b" " * (37 - len(record))).decode("ascii").encode("cp037")
                          for record in outputs)
    (folder / "input.bin").write_bytes(raw_input)
    (folder / "output.bin").write_bytes(raw_output)
    evidence = {
        "program_id": "loancalc", "dataset_id": "ibm_case", "profile_id": "zos_cp037_fb_example",
        "synthetic": True, "execution_origin": origin,
        "execution_ref": "synthetic-fb-test", "executed_at": "2026-09-26T12:00:00Z",
        "source_sha256": _hash(source.read_bytes()),
        "raw_input_sha256": _hash(raw_input), "raw_output_sha256": _hash(raw_output),
    }
    (folder / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
    return folder, evidence


def _import(workspace):
    return workflow.import_golden(
        "ibm_case", "zos_cp037_fb_example",
        "data/import_sources/ibm_case/input.bin",
        "data/import_sources/ibm_case/output.bin",
        "data/import_sources/ibm_case/evidence.json",
        root=workspace,
    )


@needs_java
def test_simulated_fb_import_preserves_raw_and_passes_java_parity(workspace):
    folder, _ = _import_sources(workspace)
    result = _import(workspace)
    assert result["status"] == "imported"
    assert result["declared_execution_origin"] == "simulated_ibm_style"
    assert (workspace / "data/imported/loancalc/ibm_case/input.bin").read_bytes() == (folder / "input.bin").read_bytes()
    assert (workspace / "data/imported/loancalc/ibm_case/output.bin").read_bytes() == (folder / "output.bin").read_bytes()
    report = workflow.compare_parity("ibm_case", root=workspace)
    assert report["status"] == "pass", report.get("errors", report.get("mismatches"))
    assert report["golden_origin"] == "imported_ibm_fixture"
    assert report["declared_execution_origin"] == "simulated_ibm_style"
    assert report["trailer_match"]
    assert _import(workspace)["status"] == "error"  # frozen; never overwrite


def test_import_rejects_changed_export_before_writing_dataset(workspace):
    folder, _ = _import_sources(workspace)
    path = folder / "output.bin"
    path.write_bytes(b"X" + path.read_bytes()[1:])
    result = _import(workspace)
    assert result["status"] == "error"
    assert "raw_output_sha256" in result["errors"][0]["message"]
    assert not (workspace / "data/inputs/ibm_case.dat").exists()


def test_import_cli_uses_same_adapter(workspace, capsys):
    _import_sources(workspace)
    args = ["ibm_case", "zos_cp037_fb_example",
            "data/import_sources/ibm_case/input.bin",
            "data/import_sources/ibm_case/output.bin",
            "data/import_sources/ibm_case/evidence.json"]
    assert import_cli.main(args) == 0
    assert '"status": "imported"' in capsys.readouterr().out
    assert import_cli.main(args) == 1


def test_import_rejects_incomplete_fb_record(workspace):
    folder, evidence = _import_sources(workspace)
    path = folder / "output.bin"
    raw = path.read_bytes()[:-1]
    path.write_bytes(raw)
    evidence["raw_output_sha256"] = _hash(raw)
    (folder / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
    result = _import(workspace)
    assert result["status"] == "error"
    assert "whole nonempty FB records" in result["errors"][0]["message"]


def test_failed_write_leaves_no_partial_import(workspace, monkeypatch):
    _import_sources(workspace)
    original_open = Path.open

    def fail_manifest_write(path, mode="r", *args, **kwargs):
        if path.name == "ibm_case.json" and mode == "xb":
            raise PermissionError("simulated write failure")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_manifest_write)
    result = _import(workspace)
    assert result["status"] == "error"
    assert not (workspace / "data/inputs/ibm_case.dat").exists()
    assert not (workspace / "data/golden/ibm_case.out").exists()
    assert not (workspace / "data/imported/loancalc/ibm_case/input.bin").exists()


def test_imported_raw_change_blocks_parity(workspace):
    _import_sources(workspace)
    assert _import(workspace)["status"] == "imported"
    path = workspace / "data/imported/loancalc/ibm_case/output.bin"
    path.write_bytes(b"X" + path.read_bytes()[1:])
    report = workflow.compare_parity("ibm_case", root=workspace)
    assert report["status"] == "error"
    assert "raw_output sha256 mismatch" in report["errors"][0]["message"]


def test_canonical_output_must_still_match_raw_export(workspace):
    _import_sources(workspace)
    assert _import(workspace)["status"] == "imported"
    golden = workspace / "data/golden/ibm_case.out"
    altered = b"X" + golden.read_bytes()[1:]
    golden.write_bytes(altered)
    manifest_path = workspace / "data/manifests/ibm_case.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["golden"]["sha256"] = _hash(altered)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = workflow.compare_parity("ibm_case", root=workspace)
    assert report["status"] == "error"
    assert "does not match archived raw records" in report["errors"][0]["message"]


def test_example_profile_cannot_claim_real_ibm_run(workspace):
    _import_sources(workspace, origin="ibm_runtime_export")
    result = _import(workspace)
    assert result["status"] == "error"
    assert "example profile" in result["errors"][0]["message"]


def test_import_rejects_source_outside_import_folder(workspace):
    _import_sources(workspace)
    result = workflow.import_golden(
        "ibm_case", "zos_cp037_fb_example", "data/inputs/ds01_normal.dat",
        "data/import_sources/ibm_case/output.bin",
        "data/import_sources/ibm_case/evidence.json", root=workspace)
    assert result["status"] == "error"
    assert "data/import_sources" in result["errors"][0]["message"]


def test_capture_does_not_replace_missing_imported_golden(workspace):
    _import_sources(workspace)
    assert _import(workspace)["status"] == "imported"
    (workspace / "data/golden/ibm_case.out").unlink()
    result = workflow.capture_golden("ibm_case", root=workspace)
    assert result["status"] == "error"
    assert "manifest exists but golden is missing" in result["errors"][0]["message"]
