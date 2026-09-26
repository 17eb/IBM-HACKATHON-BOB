"""High-level operations shared by the MCP server, the CLI, the tests and the demo app.

Every function returns a JSON-serialisable dict with `status`, `dataset_id` (where relevant),
`artifact_paths` and `errors`, and never raises for expected failures.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from adapters import local_gnucobol
from core import parity, runners
from core.paths import PathError, check_dataset_id, check_run_id, resolve_in_root, workspace_root

EXPECTED_ERRORS = (PathError, runners.RunError)


def _root(root: Path | None) -> Path:
    return (root or workspace_root()).resolve()


def _error(exc: Exception, dataset_id: str | None = None, **extra) -> dict:
    detail = exc.details if isinstance(exc, runners.RunError) else {"message": str(exc)}
    return {"status": "error", "dataset_id": dataset_id, "artifact_paths": [], "errors": [detail], **extra}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def list_datasets(root: Path | None = None) -> list[str]:
    root = _root(root)
    return sorted(p.stem for p in (root / "data" / "inputs").glob("*.dat"))


def capture_golden(dataset_id: str, profile_id: str = "loancalc_local", force_new_version: bool = False,
                   root: Path | None = None) -> dict:
    try:
        return local_gnucobol.capture_golden(_root(root), dataset_id, profile_id, force_new_version)
    except EXPECTED_ERRORS as exc:
        return _error(exc, dataset_id)


def run_candidate(dataset_id: str, candidate: str = "java", root: Path | None = None) -> dict:
    root = _root(root)
    try:
        check_dataset_id(dataset_id)
        input_path = root / "data" / "inputs" / f"{dataset_id}.dat"
        if not input_path.exists():
            raise PathError(f"no input for dataset {dataset_id!r}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%S")
        run_id = f"{candidate}-{dataset_id}-{stamp}-{secrets.token_hex(2)}"
        output_path = root / "runs" / run_id / "output.out"
        runners.run_java(root, candidate, input_path, output_path)
        return {"status": "ok", "dataset_id": dataset_id, "candidate": candidate, "run_id": run_id,
                "artifact_paths": [_rel(root, output_path)], "errors": []}
    except EXPECTED_ERRORS as exc:
        return _error(exc, dataset_id, candidate=candidate)


def compare_parity(dataset_id: str, candidate: str = "java", run_id: str | None = None,
                   root: Path | None = None) -> dict:
    root = _root(root)
    try:
        check_dataset_id(dataset_id)
        golden_path = root / "data" / "golden" / f"{dataset_id}.out"
        input_path = root / "data" / "inputs" / f"{dataset_id}.dat"
        if not golden_path.exists():
            raise PathError(f"no frozen golden for dataset {dataset_id!r}; call capture_golden first")
        if run_id is None:
            run = run_candidate(dataset_id, candidate, root)
            if run["status"] != "ok":
                return run
            run_id = run["run_id"]
        check_run_id(run_id)
        output_path = root / "runs" / run_id / "output.out"
        if not output_path.exists():
            raise PathError(f"no output for run {run_id!r}")
    except EXPECTED_ERRORS as exc:
        return _error(exc, dataset_id, candidate=candidate)

    golden, actual = golden_path.read_bytes(), output_path.read_bytes()
    input_data = input_path.read_bytes() if input_path.exists() else None
    report = {
        "dataset_id": dataset_id,
        "candidate": candidate,
        "run_id": run_id,
        "golden_origin": "local_gnucobol",
        "golden_path": _rel(root, golden_path),
        "golden_sha256": _sha256(golden),
        "candidate_sha256": _sha256(actual),
        "input_sha256": _sha256(input_data) if input_data is not None else None,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **parity.compare(golden, actual, input_data),
    }
    report_path = root / "reports" / f"{run_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    report["artifact_paths"] = [_rel(root, report_path), _rel(root, output_path)]
    report["errors"] = []
    return report


def get_run_report(run_id: str, root: Path | None = None) -> dict:
    root = _root(root)
    try:
        check_run_id(run_id)
        path = root / "reports" / f"{run_id}.json"
        if not path.exists():
            raise PathError(f"no report for run {run_id!r}")
    except EXPECTED_ERRORS as exc:
        return _error(exc)
    report = json.loads(path.read_text())
    report["artifact_paths"] = [_rel(root, path)]
    report.setdefault("errors", [])
    return report


# --- inspect_cobol: heuristic static reading of a COBOL source -------------------------------

_PARAGRAPH = re.compile(r"^ {7}([A-Z0-9][A-Z0-9-]*)\.\s*$")
_DATA_ITEM = re.compile(r"^\s+(\d\d)\s+([A-Z0-9-]+)(?:\s+PIC\s+(\S+?))?(?:\s+VALUE\s+(.+?))?\.\s*$")
_FD = re.compile(r"^\s+FD\s+([A-Z0-9-]+)")
_COMPUTE = re.compile(r"COMPUTE\s+([A-Z0-9-]+)(\s+ROUNDED)?\s*=\s*(.+)$")


def inspect_cobol(source_path: str, root: Path | None = None) -> dict:
    root = _root(root)
    try:
        path = resolve_in_root(source_path, root, must_exist=True)
        if path.suffix.lower() not in (".cbl", ".cob", ".cpy"):
            raise PathError("only .cbl, .cob or .cpy sources can be inspected")
    except EXPECTED_ERRORS as exc:
        return _error(exc)

    raw = path.read_bytes()
    lines = raw.decode("latin-1").splitlines()
    paragraphs, fields, computes, questions = [], [], [], []
    current_fd, in_procedure = None, False
    for lineno, line in enumerate(lines, start=1):
        if len(line) > 6 and line[6] in "*/":
            continue  # fixed-format comment line
        text = line[:72]
        if "PROCEDURE DIVISION" in text:
            in_procedure = True
            continue
        if not in_procedure:
            fd = _FD.match(text)
            if fd:
                current_fd = fd.group(1)
                continue
            if "WORKING-STORAGE SECTION" in text:
                current_fd = "WORKING-STORAGE"
            item = _DATA_ITEM.match(text)
            if item:
                level, name, pic, value = item.groups()
                fields.append({"line": lineno, "section": current_fd, "level": level, "name": name,
                               "pic": pic, "value": value})
            continue
        para = _PARAGRAPH.match(line)
        if para:
            paragraphs.append({"line": lineno, "name": para.group(1)})
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
    if "LINE SEQUENTIAL" in raw.decode("latin-1"):
        questions.append("LINE SEQUENTIAL files: GnuCOBOL drops trailing spaces on write and splits "
                         "over-long input lines. Check record framing in the port.")
    return {
        "status": "ok",
        "heuristic": True,
        "source_path": _rel(root, path),
        "sha256": _sha256(raw),
        "line_count": len(lines),
        "paragraphs": paragraphs,
        "data_items": fields,
        "computations": computes,
        "unresolved_questions": questions,
        "artifact_paths": [_rel(root, path)],
        "errors": [],
    }
