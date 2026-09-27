"""High-level operations shared by the MCP server, the CLI, the tests and the demo app.

Every function returns a JSON-serialisable dict with `status`, `dataset_id` (where relevant),
`artifact_paths` and `errors`, and never raises for expected failures.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

from adapters import imported_fixture, local_gnucobol
from core import fixtures, parity, programs, runners
from core.paths import PathError, check_dataset_id, check_run_id, resolve_in_root, workspace_root

EXPECTED_ERRORS = (PathError, runners.RunError)


def _root(root: Path | None) -> Path:
    return (root or workspace_root()).resolve()


def _error(exc: Exception, dataset_id: str | None = None, **extra) -> dict:
    detail = exc.details if isinstance(exc, runners.RunError) else {"message": str(exc)}
    return {"status": "error", "dataset_id": dataset_id, "artifact_paths": [], "errors": [detail], **extra}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def list_programs(root: Path | None = None) -> list[str]:
    return programs.list_programs(_root(root))


def list_datasets(root: Path | None = None, program_id: str = "loancalc") -> list[str]:
    root = _root(root)
    program = programs.load_program(root, program_id)
    return sorted(p.stem for p in program.input_dir.glob("*.dat"))


def start_cobol_port(source_path: str, input_path: str | None = None,
                     reference_output_path: str | None = None,
                     root: Path | None = None, source_format: str = "auto") -> dict:
    """Inspect an IDE workspace's COBOL program before it has a program profile.

    This read-only entry point never treats supplied output as a verified golden.
    The agent must establish its provenance and register a supported record layout
    before running parity.
    """
    root = _root(root)
    analysis = inspect_cobol(source_path, root, source_format)
    if analysis["status"] != "ok":
        return analysis
    try:
        files = {}
        for kind, rel in (("input", input_path), ("reference_output", reference_output_path)):
            if rel is None:
                continue
            path = resolve_in_root(rel, root, must_exist=True)
            if not path.is_file():
                raise PathError(f"{kind} must be a file: {rel!r}")
            files[kind] = {"path": _rel(root, path), "sha256": _sha256_file(path),
                           "bytes": path.stat().st_size}
        matches = []
        for program_id in list_programs(root):
            program = programs.load_program(root, program_id)
            if program.cobol_source == resolve_in_root(source_path, root):
                matches.append(program_id)
        return {
            "status": "ok", "workspace_root": str(root),
            "source": analysis, "files": files, "registered_programs": matches,
            "toolchain": {"cobc_available": shutil.which("cobc") is not None,
                          "javac_available": shutil.which("javac") is not None},
            "next_steps": (
                ["Call capture_interactive_golden with scripted stdin once GnuCOBOL is available.",
                 "Write a Java console port, then call verify_interactive_java for every frozen case.",
                 "Interactive verification compares exact stdout bytes, not fixed-width record fields."]
                if analysis["io_mode"] == "interactive_stdio" else
                ["Use prepare_java_port for the registered program, then verify_java_port."]
                if matches else [
                    "Read the actual COBOL source and determine input/output record framing and fields.",
                    "Create a program profile and representative input datasets in this workspace.",
                    "Capture output from the real COBOL run or import a supported IBM export; do not invent a golden.",
                    "Write the Java port and call verify_java_port only after the golden is frozen and hashed.",
                ]
            ),
            "artifact_paths": [source_path, *(item["path"] for item in files.values())],
            "errors": [],
        }
    except (PathError, OSError) as exc:
        return _error(exc)


def prepare_java_port(program_id: str = "loancalc", candidate: str = "java",
                      root: Path | None = None) -> dict:
    """Give an agent the source, target and frozen-fixture readiness for a Java port."""
    root = _root(root)
    try:
        program = programs.load_program(root, program_id)
        target = program.candidates.get(candidate)
        if target is None:
            raise PathError(f"unknown Java candidate {candidate!r} for program {program_id!r}")
        source = program.cobol_source
        if not source.is_file():
            raise PathError(f"COBOL source does not exist: {_rel(root, source)}")
        datasets = []
        for dataset_id in list_datasets(root, program_id):
            check_dataset_id(dataset_id)
            golden = program.golden_path(dataset_id)
            manifest = program.manifest_path(dataset_id)
            try:
                verified = fixtures.verify_fixture(program, dataset_id)
                fixture_error = None
            except PathError as exc:
                verified = None
                fixture_error = str(exc)
            datasets.append({
                "dataset_id": dataset_id,
                "input_path": _rel(root, program.input_path(dataset_id)),
                "golden_path": _rel(root, golden) if golden.is_file() else None,
                "manifest_path": _rel(root, manifest) if manifest.is_file() else None,
                "fixture_valid": fixture_error is None,
                "fixture_error": fixture_error,
                "golden_origin": verified.manifest["golden_origin"] if verified else None,
                "declared_execution_origin": verified.manifest.get("declared_execution_origin") if verified else None,
            })
        return {
            "status": "ok", "program_id": program_id, "candidate": candidate,
            "source_path": _rel(root, source), "source_sha256": _sha256(source.read_bytes()),
            "program_definition": f"programs/{program_id}.json",
            "java_source_dir": _rel(root, target.source_dir), "java_main_class": target.main_class,
            "datasets": datasets,
            "all_goldens_ready": bool(datasets) and all(d["fixture_valid"] for d in datasets),
            "artifact_paths": [f"programs/{program_id}.json", _rel(root, source)],
            "errors": [],
        }
    except EXPECTED_ERRORS as exc:
        return _error(exc, program_id=program_id, candidate=candidate)


def verify_java_port(program_id: str = "loancalc", candidate: str = "java",
                     root: Path | None = None) -> dict:
    """Run the Java candidate on every configured input and require all goldens to match."""
    root = _root(root)
    brief = prepare_java_port(program_id, candidate, root)
    if brief["status"] != "ok":
        return brief
    if not brief["datasets"]:
        return _error(PathError(f"no datasets for program {program_id!r}"),
                      program_id=program_id, candidate=candidate)
    results = [compare_parity(item["dataset_id"], candidate, root=root, program_id=program_id)
               for item in brief["datasets"]]
    return {
        "status": "pass" if all(item["status"] == "pass" for item in results) else "fail",
        "program_id": program_id, "candidate": candidate,
        "datasets_total": len(results),
        "datasets_passed": sum(item["status"] == "pass" for item in results),
        "mismatch_count": sum(item.get("mismatch_count", 0) for item in results),
        "results": [{key: item.get(key) for key in
                     ("dataset_id", "status", "mismatch_count", "trailer_match", "run_id", "errors")}
                    for item in results],
        "artifact_paths": [path for item in results for path in item.get("artifact_paths", [])],
        "errors": [error for item in results for error in item.get("errors", [])],
    }


def capture_golden(dataset_id: str, profile_id: str | None = None, force_new_version: bool = False,
                   root: Path | None = None, program_id: str = "loancalc") -> dict:
    try:
        root = _root(root)
        program = programs.load_program(root, program_id)
        return local_gnucobol.capture_golden(root, dataset_id, profile_id, force_new_version, program)
    except EXPECTED_ERRORS as exc:
        return _error(exc, dataset_id, program_id=program_id)


def import_golden(dataset_id: str, profile_id: str, raw_input_path: str,
                  raw_output_path: str, evidence_path: str, root: Path | None = None,
                  program_id: str = "loancalc") -> dict:
    """Import a synthetic IBM-style EBCDIC FB run as a frozen, provenance-checked fixture."""
    try:
        root = _root(root)
        program = programs.load_program(root, program_id)
        return imported_fixture.import_golden(root, program, dataset_id, profile_id,
                                              raw_input_path, raw_output_path, evidence_path)
    except (*EXPECTED_ERRORS, OSError) as exc:
        return _error(exc, dataset_id, program_id=program_id)


def run_candidate(dataset_id: str, candidate: str = "java", root: Path | None = None,
                  program_id: str = "loancalc") -> dict:
    root = _root(root)
    try:
        check_dataset_id(dataset_id)
        program = programs.load_program(root, program_id)
        input_path = program.input_path(dataset_id)
        if not input_path.exists():
            raise PathError(f"no input for dataset {dataset_id!r}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%S")
        run_id = f"{program_id[:16]}-{candidate[:16]}-{dataset_id[:24]}-{stamp}-{secrets.token_hex(3)}"
        output_path = program.output_path(run_id)
        runners.run_java(root, candidate, input_path, output_path, program)
        return {"status": "ok", "program_id": program_id, "dataset_id": dataset_id,
                "candidate": candidate, "run_id": run_id,
                "artifact_paths": [_rel(root, output_path)], "errors": []}
    except EXPECTED_ERRORS as exc:
        return _error(exc, dataset_id, candidate=candidate, program_id=program_id)


def compare_parity(dataset_id: str, candidate: str = "java", run_id: str | None = None,
                   root: Path | None = None, program_id: str = "loancalc") -> dict:
    root = _root(root)
    try:
        check_dataset_id(dataset_id)
        program = programs.load_program(root, program_id)
        golden_path = program.golden_path(dataset_id)
        if not golden_path.exists():
            raise PathError(f"no frozen golden for dataset {dataset_id!r}; call capture_golden first")
        verified = fixtures.verify_fixture(program, dataset_id)
        if run_id is None:
            run = run_candidate(dataset_id, candidate, root, program_id)
            if run["status"] != "ok":
                return run
            run_id = run["run_id"]
            verified = fixtures.verify_fixture(program, dataset_id)
        check_run_id(run_id)
        output_path = program.output_path(run_id)
        if not output_path.exists():
            raise PathError(f"no output for run {run_id!r}")
    except EXPECTED_ERRORS as exc:
        return _error(exc, dataset_id, candidate=candidate, program_id=program_id)

    golden, actual, input_data = verified.golden_data, output_path.read_bytes(), verified.input_data
    report = {
        "program_id": program_id,
        "dataset_id": dataset_id,
        "candidate": candidate,
        "run_id": run_id,
        "golden_origin": verified.manifest["golden_origin"],
        "declared_execution_origin": verified.manifest.get("declared_execution_origin"),
        "golden_path": _rel(root, golden_path),
        "golden_sha256": verified.golden_sha256,
        "fixture_manifest_sha256": verified.manifest_sha256,
        "source_sha256": verified.source_sha256,
        "candidate_sha256": _sha256(actual),
        "input_sha256": verified.input_sha256,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **parity.compare(golden, actual, input_data, program),
    }
    report_path = program.report_path(run_id)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    report["artifact_paths"] = [_rel(root, report_path), _rel(root, output_path)]
    report["errors"] = []
    return report


def get_run_report(run_id: str, root: Path | None = None, program_id: str = "loancalc") -> dict:
    root = _root(root)
    try:
        check_run_id(run_id)
        program = programs.load_program(root, program_id)
        path = program.report_path(run_id)
        if not path.exists():
            raise PathError(f"no report for run {run_id!r}")
    except EXPECTED_ERRORS as exc:
        return _error(exc, program_id=program_id)
    report = json.loads(path.read_text())
    report["artifact_paths"] = [_rel(root, path)]
    report.setdefault("errors", [])
    return report


# --- inspect_cobol: heuristic static reading of a COBOL source -------------------------------

_PARAGRAPH = re.compile(r"^ {7}([A-Z0-9][A-Z0-9-]*)\.\s*$", re.I)
_FREE_PARAGRAPH = re.compile(r"^([A-Z0-9][A-Z0-9-]*)\.\s*$", re.I)
_DATA_ITEM = re.compile(r"^\s*(\d\d)\s+([A-Z0-9-]+)(?:\s+PIC\s+(\S+?))?(?:\s+VALUE\s+(.+?))?\.\s*$", re.I)
_USAGE_ITEM = re.compile(r"^\s*(\d\d)\s+([A-Z0-9-]+)\s+(BINARY-LONG|BINARY-SHORT|BINARY-CHAR|COMP-3|COMP|COMP-5)\.\s*$", re.I)
_FD = re.compile(r"^\s*FD\s+([A-Z0-9-]+)", re.I)
_COMPUTE = re.compile(r"COMPUTE\s+([A-Z0-9-]+)(\s+ROUNDED)?\s*=\s*(.*)$", re.I)
_SELECT_ASSIGN = re.compile(r"\bSELECT\s+([A-Z0-9-]+)\s+ASSIGN\s+TO\s+([A-Z0-9-]+)", re.I)


def inspect_cobol(source_path: str, root: Path | None = None,
                  source_format: str = "auto") -> dict:
    root = _root(root)
    try:
        path = resolve_in_root(source_path, root, must_exist=True)
        if path.suffix.lower() not in (".cbl", ".cob", ".cpy"):
            raise PathError("only .cbl, .cob or .cpy sources can be inspected")
        if not path.is_file():
            raise PathError(f"COBOL source must be a file: {source_path!r}")
        if source_format not in ("auto", "free", "fixed"):
            raise PathError("source_format must be auto, free or fixed")
    except EXPECTED_ERRORS as exc:
        return _error(exc)

    raw = path.read_bytes()
    lines = raw.decode("latin-1").splitlines()
    free_format = source_format == "free" or (source_format == "auto" and any(
        re.search(r">>\s*SOURCE\s+FORMAT\s+FREE", line, re.I) for line in lines[:30]))
    paragraphs, fields, computes, questions, assignments = [], [], [], [], []
    accepts, displays = [], []
    current_fd, in_procedure = None, False
    for lineno, line in enumerate(lines, start=1):
        if not free_format and len(line) > 6 and line[6] in "*/":
            continue  # fixed-format comment line
        text = line if free_format else line[:72]
        upper = text.upper()
        if "PROCEDURE DIVISION" in upper:
            in_procedure = True
            continue
        if not in_procedure:
            selected = _SELECT_ASSIGN.search(text)
            if selected:
                assignments.append({"line": lineno, "file": selected.group(1),
                                    "assigned_to": selected.group(2)})
            fd = _FD.match(text)
            if fd:
                current_fd = fd.group(1)
                continue
            if "WORKING-STORAGE SECTION" in upper:
                current_fd = "WORKING-STORAGE"
            item = _DATA_ITEM.match(text)
            if item:
                level, name, pic, value = item.groups()
                fields.append({"line": lineno, "section": current_fd, "level": level, "name": name,
                               "pic": pic, "value": value})
            else:
                usage_item = _USAGE_ITEM.match(text)
                if usage_item:
                    level, name, usage = usage_item.groups()
                    fields.append({"line": lineno, "section": current_fd, "level": level,
                                   "name": name, "pic": None, "usage": usage, "value": None})
            continue
        para = (_FREE_PARAGRAPH if free_format else _PARAGRAPH).match(line)
        if para:
            paragraphs.append({"line": lineno, "name": para.group(1)})
        if re.search(r"\bACCEPT\b", text, re.I):
            accepts.append(lineno)
        if re.search(r"\bDISPLAY\b", text, re.I):
            displays.append(lineno)
        comp = _COMPUTE.search(text)
        if comp:
            target, rounded, expr = comp.groups()
            computes.append({"line": lineno, "target": target, "rounded": bool(rounded),
                             "expression": expr.strip()})
            if not rounded:
                questions.append(f"line {lineno}: COMPUTE {target} has no ROUNDED, so excess decimals are "
                                 f"truncated. Confirm the Java port truncates too (RoundingMode.DOWN).")
            if "/" in expr:
                questions.append(f"line {lineno}: division in COMPUTE {target}. Confirm the intermediate "
                                 f"precision matches before the final rounding.")
    if "LINE SEQUENTIAL" in raw.decode("latin-1").upper():
        questions.append("LINE SEQUENTIAL files: GnuCOBOL drops trailing spaces on write and splits "
                         "over-long input lines. Check record framing in the port.")
    io_mode = ("interactive_stdio" if accepts and not assignments else
               "file_batch" if assignments else "unknown")
    if io_mode == "interactive_stdio":
        questions.append("ACCEPT/DISPLAY interactive I/O detected. The current parity runner expects "
                         "file-path arguments and fixed-width records; use the separate "
                         "stdin/stdout transcript tools to verify this program.")
    return {
        "status": "ok",
        "heuristic": True,
        "source_path": _rel(root, path),
        "sha256": _sha256(raw),
        "line_count": len(lines),
        "source_format": "free" if free_format else "fixed",
        "io_mode": io_mode,
        "file_assignments": assignments,
        "interactive_io": {"accept_lines": accepts, "display_lines": displays},
        "paragraphs": paragraphs,
        "data_items": fields,
        "computations": computes,
        "unresolved_questions": questions,
        "artifact_paths": [_rel(root, path)],
        "errors": [],
    }
