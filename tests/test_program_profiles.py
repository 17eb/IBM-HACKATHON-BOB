"""A second layout and Java port prove the core is not wired to LOANCALC."""

import hashlib
import json

import pytest

from core import parity, workflow
from core.paths import PathError
from core.programs import load_program
from tests.conftest import needs_java
from tools import verify_all


@pytest.fixture
def tiny_program(tmp_path):
    definition = {
        "program_id": "tiny",
        "platform_profile": "tiny_local",
        "paths": {
            "inputs": "tiny/inputs", "goldens": "tiny/golden",
            "manifests": "tiny/manifests", "runs": "tiny/runs", "reports": "tiny/reports",
        },
        "cobol": {
            "source": "tiny/TINY.cbl", "binary": "tiny/build/tiny", "flags": ["-x"],
        },
        "candidates": {
            "java": {
                "source_dir": "tiny/java/src", "build_dir": "tiny/java/build",
                "main_class": "Tiny",
            },
        },
        "layout": {
            "record_format": "line_sequential_lf", "encoding": "ascii",
            "identifier_field": "ID",
            "input_fields": [{"name": "ID", "width": 2}],
            "detail_fields": [
                {"name": "ID", "width": 2, "rule": "IDENTITY"},
                {"name": "RESULT", "width": 2, "rule": "T1"},
            ],
            "trailer_prefix": "END",
            "trailer_fields": [
                {"name": "TAG", "width": 3, "rule": "T2"},
                {"name": "COUNT", "width": 2, "scale": 0, "rule": "T2"},
            ],
        },
    }
    (tmp_path / "programs").mkdir()
    (tmp_path / "programs" / "tiny.json").write_text(json.dumps(definition))
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "tiny_local.json").write_text(json.dumps({
        "system": "local", "encoding": "ascii",
        "record_format": "line_sequential_lf", "golden_origin": "local_gnucobol",
    }))
    (tmp_path / "tiny" / "inputs").mkdir(parents=True)
    (tmp_path / "tiny" / "golden").mkdir()
    (tmp_path / "tiny" / "inputs" / "case1.dat").write_bytes(b"A1\nB2\n")
    (tmp_path / "tiny" / "golden" / "case1.out").write_bytes(b"A1OK\nB2OK\nEND02\n")
    (tmp_path / "tiny" / "TINY.cbl").write_text("       IDENTIFICATION DIVISION.\n", encoding="ascii")
    (tmp_path / "tiny" / "manifests").mkdir()
    def hashed_file(rel):
        path = tmp_path / rel
        return {"path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {
        "program_id": "tiny", "dataset_id": "case1", "profile_id": "tiny_local",
        "golden_origin": "local_gnucobol",
        "source": hashed_file("tiny/TINY.cbl"),
        "input": hashed_file("tiny/inputs/case1.dat"),
        "golden": {**hashed_file("tiny/golden/case1.out"), "records": 3},
    }
    (tmp_path / "tiny" / "manifests" / "case1.json").write_text(json.dumps(manifest), encoding="utf-8")
    java_dir = tmp_path / "tiny" / "java" / "src"
    java_dir.mkdir(parents=True)
    (java_dir / "Tiny.java").write_text(
        "import java.nio.file.*;\n"
        "import java.nio.charset.StandardCharsets;\n"
        "import java.util.*;\n"
        "public class Tiny {\n"
        "  public static void main(String[] args) throws Exception {\n"
        "    List<String> input = Files.readAllLines(Path.of(args[0]));\n"
        "    List<String> output = new ArrayList<>();\n"
        "    for (String line : input) output.add(line.substring(0, 2) + \"OK\");\n"
        "    output.add(\"END\" + String.format(\"%02d\", input.size()));\n"
        "    Files.writeString(Path.of(args[1]), String.join(\"\\n\", output) + \"\\n\",\n"
        "                      StandardCharsets.US_ASCII);\n"
        "  }\n"
        "}\n"
    )
    return tmp_path


def test_second_layout_reports_its_own_fields_and_rules(tiny_program):
    program = load_program(tiny_program, "tiny")
    golden = program.golden_path("case1").read_bytes()
    candidate = golden.replace(b"A1OK", b"A1NO")
    report = parity.compare(golden, candidate, program.input_path("case1").read_bytes(), program)
    assert report["status"] == "fail"
    assert report["mismatches"][0]["field"] == "RESULT"
    assert report["mismatches"][0]["rule_id"] == "T1"
    assert report["mismatches"][0]["cust_id"] == "A1"


@needs_java
def test_second_program_runs_through_same_workflow(tiny_program):
    assert "tiny" in workflow.list_programs(tiny_program)
    assert workflow.list_datasets(tiny_program, "tiny") == ["case1"]
    report = workflow.compare_parity("case1", root=tiny_program, program_id="tiny")
    assert report["status"] == "pass", report.get("errors", report.get("mismatches"))
    assert report["records_matched"] == 2
    assert report["trailer_match"]
    assert workflow.get_run_report(report["run_id"], tiny_program, "tiny")["status"] == "pass"


@needs_java
def test_second_program_cli(tiny_program, monkeypatch, capsys):
    monkeypatch.setenv("COBOLBRIDGE_ROOT", str(tiny_program))
    assert verify_all.main(["--program", "tiny", "--candidate", "java"]) == 0
    assert "ALL DATASETS PASS" in capsys.readouterr().out


def test_program_definition_cannot_escape_workspace(tiny_program):
    path = tiny_program / "programs" / "tiny.json"
    definition = json.loads(path.read_text())
    definition["paths"]["reports"] = "../outside"
    path.write_text(json.dumps(definition))
    with pytest.raises(PathError):
        load_program(tiny_program, "tiny")
