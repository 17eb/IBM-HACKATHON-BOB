"""Bounded subprocess runners for the legacy COBOL program and the Java candidates.

All commands use fixed argument lists (never a shell), a timeout and capped output.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

TIMEOUT_S = 60
MAX_OUTPUT_CHARS = 20_000

COBOL_SOURCE = "legacy/LOANCALC.cbl"
COBOL_BINARY = "legacy/build/loancalc"
COBOL_FLAGS = ["-x", "-std=default"]

CANDIDATES = {
    "java": {"dir": "modern/java", "main": "com.cobolbridge.LoanCalc"},
    "java-naive": {"dir": "modern/java-naive", "main": "com.cobolbridge.naive.LoanCalcNaive"},
}


class RunError(RuntimeError):
    """A build or run step failed; `details` holds a structured error for callers."""

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.details = {"message": message, **details}


def _cap(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + "\n...[truncated]"


def run(args: list[str], cwd: Path, timeout: int = TIMEOUT_S, step: str = "run") -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise RunError(f"{args[0]} not found on PATH", step=step, kind="missing_tool") from None
    except subprocess.TimeoutExpired:
        raise RunError(f"{step} timed out after {timeout}s", step=step, kind="timeout") from None
    if proc.returncode != 0:
        raise RunError(
            f"{step} failed with exit code {proc.returncode}",
            step=step,
            kind="nonzero_exit",
            returncode=proc.returncode,
            stderr=_cap(proc.stderr),
            stdout=_cap(proc.stdout),
        )
    return proc


def _newest_mtime(paths: list[Path]) -> float:
    return max(p.stat().st_mtime for p in paths)


def cobc_version(root: Path) -> str:
    return run(["cobc", "--version"], root, step="cobc --version").stdout.splitlines()[0].strip()


def java_version(root: Path) -> str:
    proc = run(["java", "-version"], root, step="java -version")
    return (proc.stderr or proc.stdout).splitlines()[0].strip()


def build_cobol(root: Path) -> Path:
    source, binary = root / COBOL_SOURCE, root / COBOL_BINARY
    if not source.exists():
        raise RunError(f"COBOL source not found: {COBOL_SOURCE}", step="compile_cobol", kind="missing_source")
    if binary.exists() and binary.stat().st_mtime >= source.stat().st_mtime:
        return binary
    binary.parent.mkdir(parents=True, exist_ok=True)
    run(["cobc", *COBOL_FLAGS, "-o", str(binary), str(source)], root, step="compile_cobol")
    return binary


def run_cobol(root: Path, input_path: Path, output_path: Path) -> None:
    binary = build_cobol(root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run([str(binary), str(input_path), str(output_path)], root, step="run_cobol")


def _candidate(candidate: str) -> dict:
    if candidate not in CANDIDATES:
        raise RunError(f"unknown candidate {candidate!r}; expected one of {sorted(CANDIDATES)}",
                       step="select_candidate", kind="bad_argument")
    return CANDIDATES[candidate]


def build_java(root: Path, candidate: str) -> Path:
    spec = _candidate(candidate)
    src_dir = root / spec["dir"] / "src" / "main" / "java"
    sources = sorted(src_dir.rglob("*.java")) if src_dir.exists() else []
    if not sources:
        raise RunError(f"no Java sources for candidate {candidate!r} under {spec['dir']}/src/main/java",
                       step="compile_java", kind="missing_candidate")
    build_dir = root / spec["dir"] / "build"
    stamp = build_dir / ".built"
    if stamp.exists() and stamp.stat().st_mtime >= _newest_mtime(sources):
        return build_dir
    build_dir.mkdir(parents=True, exist_ok=True)
    run(["javac", "--release", "17", "-d", str(build_dir), *map(str, sources)], root, step="compile_java")
    stamp.touch()
    return build_dir


def run_java(root: Path, candidate: str, input_path: Path, output_path: Path) -> None:
    build_dir = build_java(root, candidate)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run(["java", "-cp", str(build_dir), _candidate(candidate)["main"], str(input_path), str(output_path)],
        root, step="run_java")
