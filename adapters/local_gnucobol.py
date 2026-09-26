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
from core.records import split_records


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_profile(root: Path, profile_id: str) -> dict:
    check_dataset_id(profile_id)  # same character rules
    path = root / "profiles" / f"{profile_id}.json"
    if not path.exists():
        raise PathError(f"unknown profile {profile_id!r}")
    profile = json.loads(path.read_text())
    missing = [k for k in ("system", "encoding", "record_format", "golden_origin") if not profile.get(k)]
    if missing:
        raise PathError(f"profile {profile_id!r} is missing required metadata: {missing}")
    return profile


def capture_golden(root: Path, dataset_id: str, profile_id: str = "loancalc_local",
                   force_new_version: bool = False) -> dict:
    check_dataset_id(dataset_id)
    profile = load_profile(root, profile_id)
    if profile["golden_origin"] != "local_gnucobol":
        raise PathError(f"profile {profile_id!r} is not a local GnuCOBOL profile")

    input_path = root / "data" / "inputs" / f"{dataset_id}.dat"
    golden_path = root / "data" / "golden" / f"{dataset_id}.out"
    manifest_path = root / "data" / "manifests" / f"{dataset_id}.json"
    if not input_path.exists():
        raise PathError(f"no input for dataset {dataset_id!r} (expected data/inputs/{dataset_id}.dat)")

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
        archive = root / "data" / "golden" / "archive" / f"{dataset_id}.{stamp}.out"
        archive.parent.mkdir(parents=True, exist_ok=True)
        supersedes = {"sha256": sha256(golden_path), "archived_as": str(archive.relative_to(root))}
        shutil.move(golden_path, archive)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_out = Path(tmp) / "golden.out"
        runners.run_cobol(root, input_path, tmp_out)
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tmp_out, golden_path)

    source_path = root / runners.COBOL_SOURCE
    records = split_records(golden_path.read_bytes())
    manifest = {
        "dataset_id": dataset_id,
        "profile_id": profile_id,
        "golden_origin": profile["golden_origin"],
        "system": profile["system"],
        "encoding": profile["encoding"],
        "record_format": profile["record_format"],
        "compiler": runners.cobc_version(root),
        "compiler_flags": runners.COBOL_FLAGS,
        "source": {"path": runners.COBOL_SOURCE, "sha256": sha256(source_path)},
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
