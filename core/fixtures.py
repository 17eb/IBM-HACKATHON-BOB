"""Validate frozen fixture bytes and provenance before parity can use them."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from core.paths import PathError, check_dataset_id
from core.platform_profiles import load_profile
from core.programs import Program
from core.records import split_records

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class VerifiedFixture:
    manifest: dict
    manifest_sha256: str
    source_sha256: str
    input_sha256: str
    golden_sha256: str
    input_data: bytes
    golden_data: bytes


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checked_file(program: Program, entry: object, expected_path: Path, label: str) -> tuple[bytes, str]:
    if not isinstance(entry, dict):
        raise PathError(f"manifest {label} must be an object")
    expected_relative = expected_path.relative_to(program.root).as_posix()
    if not expected_path.resolve().is_relative_to(program.root):
        raise PathError(f"{label} path escapes the workspace root")
    if entry.get("path") != expected_relative:
        raise PathError(f"manifest {label} path must be {expected_relative!r}")
    expected_hash = entry.get("sha256")
    if not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash):
        raise PathError(f"manifest {label} sha256 is missing or invalid")
    if not expected_path.is_file():
        raise PathError(f"{label} file is missing: {expected_relative}")
    data = expected_path.read_bytes()
    actual_hash = _digest(data)
    if actual_hash != expected_hash:
        raise PathError(
            f"{label} sha256 mismatch for {expected_relative}: "
            f"manifest {expected_hash}, actual {actual_hash}"
        )
    return data, actual_hash


def verify_fixture(program: Program, dataset_id: str) -> VerifiedFixture:
    """Require a complete manifest and exact source/input/golden bytes for one dataset."""
    check_dataset_id(dataset_id)
    manifest_path = program.manifest_path(dataset_id)
    if not manifest_path.is_file():
        raise PathError(f"no manifest for dataset {dataset_id!r}; capture_golden first")
    raw_manifest = manifest_path.read_bytes()
    try:
        manifest = json.loads(raw_manifest.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PathError(f"invalid manifest for dataset {dataset_id!r}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise PathError(f"manifest for dataset {dataset_id!r} must be an object")
    if manifest.get("dataset_id") != dataset_id:
        raise PathError(f"manifest dataset_id does not match {dataset_id!r}")
    if manifest.get("program_id", program.program_id) != program.program_id:
        raise PathError(f"manifest program_id does not match {program.program_id!r}")
    profile_id = manifest.get("profile_id")
    profile = load_profile(program.root, profile_id)
    if not isinstance(manifest.get("golden_origin"), str) or not manifest["golden_origin"]:
        raise PathError("manifest golden_origin is missing")
    if profile["golden_origin"] != manifest["golden_origin"]:
        raise PathError("manifest golden_origin does not match its profile")
    if profile_id != program.platform_profile and manifest["golden_origin"] != "imported_ibm_fixture":
        raise PathError("only imported IBM fixtures may use a nondefault platform profile")
    for key in ("system", "encoding", "record_format"):
        if key in manifest and (not isinstance(manifest[key], str) or
                                manifest[key].lower() != profile[key].lower()):
            raise PathError(f"manifest {key} does not match its profile")

    _, source_hash = _checked_file(program, manifest.get("source"), program.cobol_source, "source")
    input_data, input_hash = _checked_file(program, manifest.get("input"), program.input_path(dataset_id), "input")
    golden_data, golden_hash = _checked_file(program, manifest.get("golden"), program.golden_path(dataset_id), "golden")
    record_count = manifest["golden"].get("records")
    if not isinstance(record_count, int) or isinstance(record_count, bool) or record_count < 0:
        raise PathError("manifest golden.records is missing or invalid")
    if len(split_records(golden_data)) != record_count:
        raise PathError(f"golden record count disagrees with manifest for dataset {dataset_id!r}")
    if manifest["golden_origin"] == "imported_ibm_fixture":
        from adapters import imported_fixture

        if profile["system"] not in ("zos", "ibmi"):
            raise PathError("imported IBM fixture profile must declare zos or ibmi")
        for key in ("system", "encoding", "record_format", "compiler"):
            if key not in manifest:
                raise PathError(f"imported fixture manifest is missing {key}")
        for key in ("input_lrecl", "output_lrecl", "compiler_options"):
            if manifest.get(key) != profile.get(key):
                raise PathError(f"imported fixture manifest {key} does not match its profile")
        if manifest.get("compiler") != profile.get("compiler"):
            raise PathError("imported fixture manifest compiler does not match its profile")
        if profile.get("source") != program.cobol_source.relative_to(program.root).as_posix():
            raise PathError("imported fixture profile source does not match configured COBOL source")
        archive = program.root / "data" / "imported" / program.program_id / dataset_id
        raw_input, raw_input_hash = _checked_file(
            program, manifest.get("raw_input"), archive / "input.bin", "raw_input")
        raw_output, raw_output_hash = _checked_file(
            program, manifest.get("raw_output"), archive / "output.bin", "raw_output")
        evidence_raw, _ = _checked_file(
            program, manifest.get("evidence"), archive / "evidence.json", "evidence")
        evidence = imported_fixture.validate_evidence(
            evidence_raw, program, dataset_id, profile_id, source_hash,
            raw_input_hash, raw_output_hash)
        if manifest.get("declared_execution_origin") != evidence["execution_origin"]:
            raise PathError("manifest declared_execution_origin does not match evidence")
        if evidence["execution_origin"] == "ibm_runtime_export" and profile.get("example_only") is True:
            raise PathError("example platform profile cannot describe an IBM runtime export")
        decoded_input, decoded_output, decoded_count = imported_fixture.decode_fb_export(
            program, profile, raw_input, raw_output)
        if decoded_input != input_data or decoded_output != golden_data or decoded_count != record_count:
            raise PathError("decoded IBM fixture does not match archived raw records")
    return VerifiedFixture(manifest, _digest(raw_manifest), source_hash, input_hash, golden_hash,
                           input_data, golden_data)
