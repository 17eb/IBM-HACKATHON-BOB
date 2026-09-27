"""Legacy adapter: capture a frozen COBOL golden by running LOANCALC locally with GnuCOBOL."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core import runners
from core.paths import PathError, check_dataset_id
from core.platform_profiles import load_profile
from core.programs import Program, load_program
from core.records import split_records


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture_golden(root: Path, dataset_id: str, profile_id: str | None = None,
                   force_new_version: bool = False, program: Program | None = None) -> dict:
    check_dataset_id(dataset_id)
    program = program or load_program(root)
    profile_id = profile_id or program.platform_profile
    if profile_id != program.platform_profile:
        raise PathError(f"local capture profile must be {program.platform_profile!r}")
    profile = load_profile(root, profile_id)
    if profile["golden_origin"] != "local_gnucobol":
        raise PathError(f"profile {profile_id!r} is not a local GnuCOBOL profile")

    input_path = program.input_path(dataset_id)
    golden_path = program.golden_path(dataset_id)
    manifest_path = program.manifest_path(dataset_id)
    if not input_path.exists():
        raise PathError(f"no input for dataset {dataset_id!r} (expected {input_path.relative_to(root)})")
    if manifest_path.exists() and not golden_path.exists():
        raise PathError(f"manifest exists but golden is missing for dataset {dataset_id!r}")

    supersedes = None
    if golden_path.exists():
        if not force_new_version:
            return {
                "status": "frozen",
                "dataset_id": dataset_id,
                "artifact_paths": [str(golden_path.relative_to(root)), str(manifest_path.relative_to(root))],
                "errors": ["golden already frozen; pass force_new_version=true with a documented reason"],
            }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = program.golden_dir / "archive" / f"{dataset_id}.{stamp}.out"
        archive.parent.mkdir(parents=True, exist_ok=True)
        supersedes = {"sha256": sha256(golden_path), "archived_as": str(archive.relative_to(root))}
        shutil.move(golden_path, archive)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_out = Path(tmp) / "golden.out"
        runners.run_cobol(root, input_path, tmp_out, program)
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tmp_out, golden_path)

    source_path = program.cobol_source
    records = split_records(golden_path.read_bytes())
    manifest = {
        "program_id": program.program_id,
        "dataset_id": dataset_id,
        "profile_id": profile_id,
        "golden_origin": profile["golden_origin"],
        "system": profile["system"],
        "encoding": profile["encoding"],
        "record_format": profile["record_format"],
        "compiler": runners.cobc_version(root),
        "compiler_flags": list(program.cobol_flags),
        "source": {"path": str(source_path.relative_to(root)), "sha256": sha256(source_path)},
        "input": {"path": str(input_path.relative_to(root)), "sha256": sha256(input_path)},
        "golden": {"path": str(golden_path.relative_to(root)), "sha256": sha256(golden_path),
                   "records": len(records)},
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "supersedes": supersedes,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return {
        "status": "captured",
        "dataset_id": dataset_id,
        "artifact_paths": [str(golden_path.relative_to(root)), str(manifest_path.relative_to(root))],
        "manifest": manifest,
        "errors": [],
    }
