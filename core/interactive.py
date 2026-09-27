"""Golden capture and exact stdout parity for interactive COBOL programs.

This is separate from the fixed-width batch profile runner. Each case supplies
scripted stdin; the COBOL and Java processes receive identical bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core.paths import PathError, check_dataset_id, resolve_in_root

SCHEMA = "cobol-bridge-interactive-v1"
TIMEOUT_SECONDS = 60
MAX_INPUT_BYTES = 64_000
MAX_OUTPUT_BYTES = 1_000_000
_JAVA_CLASS = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _error(message: str, **details) -> dict:
    return {"status": "error", "artifact_paths": [],
            "errors": [{"message": message, **details}]}


def _source(root: Path, source_path: str) -> Path:
    source = resolve_in_root(source_path, root, must_exist=True)
    if not source.is_file() or source.suffix.lower() not in (".cbl", ".cob"):
        raise PathError("source must be a .cbl or .cob file in the configured workspace")
    return source


def _case_dir(root: Path, source: Path, case_id: str) -> Path:
    check_dataset_id(case_id)
    source_key = _hash(_rel(root, source).encode("utf-8"))[:16]
    path = root / ".cobol-bridge" / "transcripts" / source_key / case_id
    if not path.resolve().is_relative_to(root):
        raise PathError("interactive case path escapes workspace root")
    return path


def _run(args: list[str], root: Path, *, stdin: bytes | None = None,
         step: str) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(args, cwd=root, input=stdin, capture_output=True,
                                timeout=TIMEOUT_SECONDS)
    except FileNotFoundError:
        raise PathError(f"{args[0]} not found on PATH") from None
    except subprocess.TimeoutExpired:
        raise PathError(f"{step} timed out after {TIMEOUT_SECONDS}s") from None
    if len(result.stdout) > MAX_OUTPUT_BYTES or len(result.stderr) > MAX_OUTPUT_BYTES:
        raise PathError(f"{step} output exceeded {MAX_OUTPUT_BYTES} bytes")
    if result.returncode != 0:
        raise PathError(f"{step} exited {result.returncode}: "
                        f"{result.stderr[:2000].decode('utf-8', errors='replace')}")
    return result


def _verified_case(root: Path, source: Path, case_id: str) -> tuple[Path, dict, bytes, bytes]:
    case_dir = _case_dir(root, source, case_id)
    manifest_path = case_dir / "manifest.json"
    if not manifest_path.is_file():
        raise PathError(f"no frozen interactive golden for case {case_id!r}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PathError(f"invalid interactive manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA or manifest.get("case_id") != case_id:
        raise PathError("interactive manifest schema or case_id mismatch")
    if manifest.get("origin") != "local_gnucobol":
        raise PathError("interactive golden origin is not a local GnuCOBOL capture")
    expected = {"source": source, "stdin": case_dir / "stdin.txt",
                "golden": case_dir / "golden.stdout"}
    data = {}
    for label, path in expected.items():
        item = manifest.get(label)
        if not isinstance(item, dict) or item.get("path") != _rel(root, path):
            raise PathError(f"interactive {label} path mismatch")
        if not path.resolve().is_relative_to(root):
            raise PathError(f"interactive {label} path escapes workspace root")
        if not path.is_file():
            raise PathError(f"interactive {label} is missing")
        value = path.read_bytes()
        if _hash(value) != item.get("sha256"):
            raise PathError(f"interactive {label} sha256 mismatch")
        data[label] = value
    return case_dir, manifest, data["stdin"], data["golden"]


def capture_golden(source_path: str, case_id: str, stdin_text: str,
                   root: Path, source_format: str = "auto") -> dict:
    """Run real GnuCOBOL once and freeze a scripted interactive session."""
    root = root.resolve()
    try:
        source = _source(root, source_path)
        if not isinstance(stdin_text, str):
            raise PathError("stdin_text must be text")
        stdin = stdin_text.encode("utf-8")
        if len(stdin) > MAX_INPUT_BYTES:
            raise PathError(f"stdin_text exceeds {MAX_INPUT_BYTES} bytes")
        case_dir = _case_dir(root, source, case_id)
        if case_dir.exists():
            _, _, frozen_stdin, _ = _verified_case(root, source, case_id)
            if frozen_stdin != stdin:
                raise PathError("case already frozen with different stdin; use a new case_id")
            return {"status": "frozen", "case_id": case_id,
                    "artifact_paths": [_rel(root, case_dir / "manifest.json")], "errors": []}

        from core.workflow import inspect_cobol
        analysis = inspect_cobol(_rel(root, source), root, source_format)
        if analysis["status"] != "ok":
            raise PathError(analysis["errors"][0]["message"])
        flags = ["-x"] + (["-free"] if analysis["source_format"] == "free" else [])
        version = _run(["cobc", "--version"], root, step="cobc --version")
        with tempfile.TemporaryDirectory(dir=root) as temp:
            binary = Path(temp) / ("cobol-program.exe" if os.name == "nt" else "cobol-program")
            _run(["cobc", *flags, "-o", str(binary), str(source)], root, step="compile COBOL")
            output = _run([str(binary)], root, stdin=stdin, step="run COBOL").stdout

        case_dir.mkdir(parents=True, exist_ok=False)
        input_path, golden_path = case_dir / "stdin.txt", case_dir / "golden.stdout"
        input_path.write_bytes(stdin)
        golden_path.write_bytes(output)
        manifest = {
            "schema": SCHEMA, "case_id": case_id, "origin": "local_gnucobol",
            "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "compiler": (version.stdout.splitlines() or [b"unknown"])[0].decode(
                "utf-8", errors="replace"),
            "compiler_flags": flags,
            "source": {"path": _rel(root, source), "sha256": _hash(source.read_bytes())},
            "stdin": {"path": _rel(root, input_path), "sha256": _hash(stdin)},
            "golden": {"path": _rel(root, golden_path), "sha256": _hash(output)},
        }
        manifest_path = case_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return {"status": "captured", "case_id": case_id,
                "golden_sha256": manifest["golden"]["sha256"],
                "artifact_paths": [_rel(root, input_path), _rel(root, golden_path),
                                   _rel(root, manifest_path)], "errors": []}
    except (PathError, OSError) as exc:
        return _error(str(exc), case_id=case_id)


def verify_java(source_path: str, case_id: str, java_source_dir: str,
                main_class: str, root: Path) -> dict:
    """Run Java with the frozen stdin and compare exact stdout bytes."""
    root = root.resolve()
    try:
        source = _source(root, source_path)
        case_dir, manifest, stdin, golden = _verified_case(root, source, case_id)
        if not isinstance(main_class, str) or not _JAVA_CLASS.fullmatch(main_class):
            raise PathError("invalid Java main_class")
        java_dir = resolve_in_root(java_source_dir, root, must_exist=True)
        if not java_dir.is_dir():
            raise PathError("java_source_dir must be a directory")
        sources = sorted(java_dir.rglob("*.java"))
        if not sources:
            raise PathError("no Java files in java_source_dir")
        if any(not item.resolve().is_relative_to(root) for item in sources):
            raise PathError("Java source path escapes workspace root")
        with tempfile.TemporaryDirectory(dir=root) as temp:
            _run(["javac", "--release", "17", "-d", temp, *map(str, sources)],
                 root, step="compile Java")
            actual = _run(["java", "-cp", temp, main_class], root, stdin=stdin,
                          step="run Java").stdout

        first_difference = next((i for i, pair in enumerate(zip(golden, actual))
                                 if pair[0] != pair[1]), min(len(golden), len(actual)))
        matched = actual == golden
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%S") + "-" + secrets.token_hex(3)
        run_dir = case_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        output_path, report_path = run_dir / "java.stdout", run_dir / "report.json"
        output_path.write_bytes(actual)
        report = {
            "status": "pass" if matched else "fail", "case_id": case_id,
            "source_path": _rel(root, source), "java_source_dir": _rel(root, java_dir),
            "main_class": main_class, "golden_origin": manifest["origin"],
            "golden_sha256": manifest["golden"]["sha256"],
            "candidate_sha256": _hash(actual), "bytes_expected": len(golden),
            "bytes_actual": len(actual),
            "first_difference_byte": None if matched else first_difference,
            "artifact_paths": [_rel(root, output_path), _rel(root, report_path)],
            "errors": [],
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    except (PathError, OSError) as exc:
        return _error(str(exc), case_id=case_id)
