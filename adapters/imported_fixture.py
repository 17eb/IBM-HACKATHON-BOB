"""Import synthetic IBM-style EBCDIC FB exports without running a remote system."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from core.paths import PathError, check_dataset_id, resolve_in_root
from core.platform_profiles import load_profile
from core.programs import Program
from core.records import Field

_ENCODINGS = {"cp037", "cp500", "cp1140"}
_ORIGINS = {"simulated_ibm_style", "ibm_runtime_export"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_entry(root: Path, path: Path, data: bytes) -> dict:
    return {"path": path.relative_to(root).as_posix(), "sha256": _sha256(data)}


def _source_file(root: Path, relative: str) -> tuple[Path, bytes]:
    path = resolve_in_root(relative, root, must_exist=True)
    allowed = (root / "data" / "import_sources").resolve()
    if not path.is_file() or not path.is_relative_to(allowed):
        raise PathError("import files must be under data/import_sources/")
    return path, path.read_bytes()


def _positive_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise PathError(f"{label} must be a positive integer")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PathError(f"{label} must be a nonempty string")
    return value


def _records(raw: bytes, lrecl: int, label: str) -> list[bytes]:
    if not raw or len(raw) % lrecl:
        raise PathError(f"{label} must contain whole nonempty FB records of LRECL {lrecl}")
    return [raw[pos:pos + lrecl] for pos in range(0, len(raw), lrecl)]


def _decode(record: bytes, encoding: str, canonical_encoding: str, label: str) -> bytes:
    try:
        result = record.decode(encoding).encode(canonical_encoding)
    except (UnicodeError, LookupError) as exc:
        raise PathError(f"{label} cannot be decoded to {canonical_encoding}: {exc}") from exc
    if b"\n" in result or b"\r" in result:
        raise PathError(f"{label} contains a line break inside an FB record")
    return result


def _check_display_numbers(record: bytes, fields: tuple[Field, ...], label: str) -> None:
    for field in fields:
        if field.scale is not None:
            value = record[field.slice]
            if not value.isascii() or not value.isdigit():
                raise PathError(f"{label} {field.name} is not display numeric; packed/binary fields are unsupported")


def validate_evidence(raw: bytes, program: Program, dataset_id: str, profile_id: str,
                      source_hash: str, input_hash: str, output_hash: str) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PathError(f"invalid import evidence: {exc}") from exc
    if not isinstance(value, dict):
        raise PathError("import evidence must be an object")
    required = {
        "program_id": program.program_id,
        "dataset_id": dataset_id,
        "profile_id": profile_id,
        "source_sha256": source_hash,
        "raw_input_sha256": input_hash,
        "raw_output_sha256": output_hash,
    }
    for key, expected in required.items():
        actual = value.get(key)
        if key.endswith("sha256") and isinstance(actual, str):
            actual = actual.lower()
        if actual != expected:
            raise PathError(f"import evidence {key} does not match the supplied file or program")
    if value.get("synthetic") is not True:
        raise PathError("only synthetic IBM fixture data may be imported")
    if value.get("execution_origin") not in _ORIGINS:
        raise PathError(f"execution_origin must be one of {sorted(_ORIGINS)}")
    _text(value.get("execution_ref"), "execution_ref")
    stamp = _text(value.get("executed_at"), "executed_at")
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PathError("executed_at must be an ISO 8601 timestamp") from exc
    if moment.tzinfo is None:
        raise PathError("executed_at must include a timezone")
    return value


def decode_fb_export(program: Program, profile: dict, raw_input: bytes,
                     raw_output: bytes) -> tuple[bytes, bytes, int]:
    """Decode only declared single-byte display fields; retain record widths and padding."""
    if profile["record_format"] != "FB":
        raise PathError("only EBCDIC FB imports are supported; VB and line sequential require another adapter")
    encoding = profile["encoding"].lower()
    if encoding not in _ENCODINGS:
        raise PathError(f"unsupported EBCDIC encoding {encoding!r}; supported: {sorted(_ENCODINGS)}")
    input_lrecl = _positive_integer(profile.get("input_lrecl"), "input_lrecl")
    output_lrecl = _positive_integer(profile.get("output_lrecl"), "output_lrecl")
    input_width = sum(field.width for field in program.input_fields)
    detail_width = sum(field.width for field in program.detail_fields)
    trailer_width = sum(field.width for field in program.trailer_fields)
    if input_lrecl != input_width or output_lrecl != detail_width or trailer_width > output_lrecl:
        raise PathError("FB LRECL values must match the configured input/detail layout widths")
    input_records = [_decode(record, encoding, program.encoding, "input record")
                     for record in _records(raw_input, input_lrecl, "raw input")]
    for record in input_records:
        _check_display_numbers(record, program.input_fields, "input")
    output_records = [_decode(record, encoding, program.encoding, "output record")
                      for record in _records(raw_output, output_lrecl, "raw output")]
    if program.trailer_fields:
        trailer = output_records[-1]
        if not trailer.startswith(program.trailer_prefix):
            raise PathError("last FB output record does not contain the configured trailer")
        if trailer[trailer_width:] != b" " * (output_lrecl - trailer_width):
            raise PathError("FB trailer padding is not all spaces")
        output_records[-1] = trailer[:trailer_width]
        _check_display_numbers(output_records[-1], program.trailer_fields, "trailer")
        detail_records = output_records[:-1]
    else:
        detail_records = output_records
    for record in detail_records:
        _check_display_numbers(record, program.detail_fields, "output")
    return (b"\n".join(input_records) + b"\n",
            b"\n".join(output_records) + b"\n", len(output_records))


def import_golden(root: Path, program: Program, dataset_id: str, profile_id: str,
                  raw_input_path: str, raw_output_path: str, evidence_path: str) -> dict:
    """Freeze an EBCDIC FB export and its exact decoded comparison files."""
    check_dataset_id(dataset_id)
    profile = load_profile(root, profile_id)
    if profile["system"] not in ("zos", "ibmi") or profile["golden_origin"] != "imported_ibm_fixture":
        raise PathError("import profile must declare an IBM system and imported_ibm_fixture origin")
    if profile.get("source") != program.cobol_source.relative_to(root).as_posix():
        raise PathError("import profile source does not match the configured COBOL source")
    _text(profile.get("compiler"), "profile.compiler")
    options = profile.get("compiler_options")
    if not isinstance(options, list) or not all(isinstance(x, str) and x for x in options):
        raise PathError("profile.compiler_options must be a list of strings")
    input_lrecl = _positive_integer(profile.get("input_lrecl"), "input_lrecl")
    output_lrecl = _positive_integer(profile.get("output_lrecl"), "output_lrecl")

    input_source, raw_input = _source_file(root, raw_input_path)
    output_source, raw_output = _source_file(root, raw_output_path)
    evidence_source, raw_evidence = _source_file(root, evidence_path)
    if len({input_source, output_source, evidence_source}) != 3:
        raise PathError("input, output and evidence must be different files")
    if not program.cobol_source.is_file():
        raise PathError("configured COBOL source is missing")
    source_data = program.cobol_source.read_bytes()
    evidence = validate_evidence(raw_evidence, program, dataset_id, profile_id,
                                 _sha256(source_data), _sha256(raw_input), _sha256(raw_output))
    if evidence["execution_origin"] == "ibm_runtime_export" and profile.get("example_only") is True:
        raise PathError("an IBM runtime export requires a real platform profile, not the example profile")

    canonical_input, canonical_output, record_count = decode_fb_export(program, profile, raw_input, raw_output)

    input_path = program.input_path(dataset_id)
    golden_path = program.golden_path(dataset_id)
    manifest_path = program.manifest_path(dataset_id)
    archive_dir = root / "data" / "imported" / program.program_id / dataset_id
    raw_input_target = archive_dir / "input.bin"
    raw_output_target = archive_dir / "output.bin"
    evidence_target = archive_dir / "evidence.json"
    targets = (input_path, golden_path, manifest_path, raw_input_target, raw_output_target, evidence_target)
    existing = [path.relative_to(root).as_posix() for path in targets if path.exists()]
    if existing:
        raise PathError(f"import refuses to overwrite existing dataset files: {existing}")

    manifest = {
        "program_id": program.program_id, "dataset_id": dataset_id, "profile_id": profile_id,
        "golden_origin": "imported_ibm_fixture", "declared_execution_origin": evidence["execution_origin"],
        "system": profile["system"], "encoding": profile["encoding"].lower(), "record_format": "FB",
        "input_lrecl": input_lrecl, "output_lrecl": output_lrecl,
        "compiler": profile["compiler"], "compiler_options": options,
        "source": _file_entry(root, program.cobol_source, source_data),
        "input": _file_entry(root, input_path, canonical_input),
        "golden": {**_file_entry(root, golden_path, canonical_output), "records": record_count},
        "raw_input": _file_entry(root, raw_input_target, raw_input),
        "raw_output": _file_entry(root, raw_output_target, raw_output),
        "evidence": _file_entry(root, evidence_target, raw_evidence),
        "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    writes = ((raw_input_target, raw_input), (raw_output_target, raw_output),
              (evidence_target, raw_evidence), (input_path, canonical_input),
              (golden_path, canonical_output),
              (manifest_path, (json.dumps(manifest, indent=2) + "\n").encode("utf-8")))
    created: list[Path] = []
    try:
        for path, data in writes:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                created.append(path)
                output.write(data)
    except OSError:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return {
        "status": "imported", "program_id": program.program_id, "dataset_id": dataset_id,
        "profile_id": profile_id, "declared_execution_origin": evidence["execution_origin"],
        "artifact_paths": [path.relative_to(root).as_posix() for path in targets],
        "errors": [],
    }
