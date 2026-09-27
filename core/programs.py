"""Validated, data-driven definitions for fixed-width batch programs.

Adding a program requires a JSON definition, source files and test data; the
runner and parity checker do not need program-specific Python branches.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from core.paths import PathError, check_dataset_id, resolve_in_root
from core.records import Field

_ID = re.compile(r"^[a-z0-9_]{1,64}$")
_CANDIDATE_ID = re.compile(r"^[a-z0-9_-]{1,64}$")
_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_JAVA_CLASS = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$")
_OPERATORS = {"gt", "ge", "eq", "le", "lt"}


@dataclass(frozen=True)
class JavaCandidate:
    source_dir: Path
    build_dir: Path
    main_class: str


@dataclass(frozen=True)
class RuleOverride:
    output_field: str
    input_field: Field
    operator: str
    value: int
    rule_id: str


@dataclass(frozen=True)
class Program:
    program_id: str
    root: Path
    platform_profile: str
    input_dir: Path
    golden_dir: Path
    manifest_dir: Path
    run_dir: Path
    report_dir: Path
    cobol_source: Path
    cobol_binary: Path
    cobol_flags: tuple[str, ...]
    encoding: str
    candidates: dict[str, JavaCandidate]
    input_fields: tuple[Field, ...]
    detail_fields: tuple[Field, ...]
    trailer_fields: tuple[Field, ...]
    trailer_prefix: bytes | None
    identifier_field: Field
    rule_overrides: tuple[RuleOverride, ...]

    def input_path(self, dataset_id: str) -> Path:
        return self.input_dir / f"{check_dataset_id(dataset_id)}.dat"

    def golden_path(self, dataset_id: str) -> Path:
        return self.golden_dir / f"{check_dataset_id(dataset_id)}.out"

    def manifest_path(self, dataset_id: str) -> Path:
        return self.manifest_dir / f"{check_dataset_id(dataset_id)}.json"

    def output_path(self, run_id: str) -> Path:
        return self.run_dir / run_id / "output.out"

    def report_path(self, run_id: str) -> Path:
        return self.report_dir / f"{run_id}.json"


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise PathError(f"{label} must be an object")
    return value


def _path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str):
        raise PathError(f"{label} must be a workspace-relative path")
    return resolve_in_root(value, root)


def _fields(value: object, label: str, required: bool = True) -> tuple[Field, ...]:
    if not isinstance(value, list) or (required and not value):
        raise PathError(f"{label} must be a {'nonempty ' if required else ''}list")
    fields: list[Field] = []
    seen: set[str] = set()
    start = 1
    for item in value:
        data = _object(item, f"{label} field")
        name, width = data.get("name"), data.get("width")
        if not isinstance(name, str) or not _FIELD.fullmatch(name) or name in seen:
            raise PathError(f"invalid or duplicate field name in {label}: {name!r}")
        if not isinstance(width, int) or isinstance(width, bool) or width < 1:
            raise PathError(f"{label}.{name} width must be positive")
        scale = data.get("scale")
        if scale is not None and (not isinstance(scale, int) or isinstance(scale, bool) or scale < 0):
            raise PathError(f"{label}.{name} scale must be nonnegative")
        rule = data.get("rule")
        if rule is not None and (not isinstance(rule, str) or not rule):
            raise PathError(f"{label}.{name} rule must be a nonempty string")
        fields.append(Field(name, start, width, scale, rule))
        seen.add(name)
        start += width
    return tuple(fields)


def list_programs(root: Path) -> list[str]:
    return sorted(p.stem for p in (root / "programs").glob("*.json") if _ID.fullmatch(p.stem))


def load_program(root: Path, program_id: str = "loancalc") -> Program:
    root = root.resolve()
    if not isinstance(program_id, str) or not _ID.fullmatch(program_id):
        raise PathError(f"invalid program_id {program_id!r}")
    path = root / "programs" / f"{program_id}.json"
    if not path.is_file():
        raise PathError(f"unknown program {program_id!r}; expected {path.relative_to(root)}")
    try:
        data = _object(json.loads(path.read_text(encoding="utf-8")), "program")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PathError(f"cannot read program definition {program_id!r}: {exc}") from exc
    if data.get("program_id") != program_id:
        raise PathError(f"program_id in {path.name} must be {program_id!r}")
    platform_profile = data.get("platform_profile")
    if not isinstance(platform_profile, str) or not _ID.fullmatch(platform_profile):
        raise PathError("platform_profile must be a lowercase identifier")

    paths = _object(data.get("paths"), "paths")
    required_dirs = ("inputs", "goldens", "manifests", "runs", "reports")
    dirs = {key: _path(root, paths.get(key), f"paths.{key}") for key in required_dirs}

    cobol = _object(data.get("cobol"), "cobol")
    flags = cobol.get("flags")
    if not isinstance(flags, list) or not all(isinstance(flag, str) and flag.startswith("-") for flag in flags):
        raise PathError("cobol.flags must be a list of compiler flags")
    candidates_data = _object(data.get("candidates"), "candidates")
    if not candidates_data:
        raise PathError("candidates must contain at least one Java port")
    candidates: dict[str, JavaCandidate] = {}
    for name, value in candidates_data.items():
        if not isinstance(name, str) or not _CANDIDATE_ID.fullmatch(name):
            raise PathError(f"invalid candidate name {name!r}")
        spec = _object(value, f"candidate {name}")
        main_class = spec.get("main_class")
        if not isinstance(main_class, str) or not _JAVA_CLASS.fullmatch(main_class):
            raise PathError(f"candidate {name} has invalid main_class")
        candidates[name] = JavaCandidate(
            _path(root, spec.get("source_dir"), f"candidate {name}.source_dir"),
            _path(root, spec.get("build_dir"), f"candidate {name}.build_dir"),
            main_class,
        )

    layout = _object(data.get("layout"), "layout")
    if layout.get("record_format") != "line_sequential_lf":
        raise PathError("only line_sequential_lf record format is supported")
    if layout.get("encoding") not in ("ascii", "latin-1"):
        raise PathError("only ascii and latin-1 single-byte encodings are supported")
    input_fields = _fields(layout.get("input_fields"), "input_fields")
    detail_fields = _fields(layout.get("detail_fields"), "detail_fields")
    trailer_fields = _fields(layout.get("trailer_fields", []), "trailer_fields", required=False)
    id_name = layout.get("identifier_field")
    id_field = next((field for field in detail_fields if field.name == id_name), None)
    if id_field is None:
        raise PathError("identifier_field must name a detail field")
    prefix = layout.get("trailer_prefix")
    if trailer_fields:
        if not isinstance(prefix, str) or not prefix or len(prefix) > sum(f.width for f in trailer_fields):
            raise PathError("trailer_prefix is required and must fit the trailer layout")
        try:
            prefix_bytes = prefix.encode("ascii")
        except UnicodeEncodeError as exc:
            raise PathError("trailer_prefix must be ASCII") from exc
    else:
        if prefix is not None:
            raise PathError("trailer_prefix requires trailer_fields")
        prefix_bytes = None

    overrides: list[RuleOverride] = []
    input_by_name = {field.name: field for field in input_fields}
    detail_names = {field.name for field in detail_fields}
    for item in layout.get("rule_overrides", []):
        rule = _object(item, "rule_override")
        input_field = input_by_name.get(rule.get("input_field"))
        output_field = rule.get("output_field")
        operator, value, rule_id = rule.get("operator"), rule.get("value"), rule.get("rule_id")
        if input_field is None or input_field.scale not in (None, 0) or output_field not in detail_names:
            raise PathError("rule_override must name a detail field and an integer input field")
        if operator not in _OPERATORS or not isinstance(value, int) or isinstance(value, bool):
            raise PathError("rule_override needs an integer threshold and supported operator")
        if not isinstance(rule_id, str) or not rule_id:
            raise PathError("rule_override needs a rule_id")
        overrides.append(RuleOverride(output_field, input_field, operator, value, rule_id))

    return Program(
        program_id, root, platform_profile,
        dirs["inputs"], dirs["goldens"], dirs["manifests"], dirs["runs"], dirs["reports"],
        _path(root, cobol.get("source"), "cobol.source"),
        _path(root, cobol.get("binary"), "cobol.binary"),
        tuple(flags), layout["encoding"], candidates, input_fields, detail_fields, trailer_fields,
        prefix_bytes, id_field, tuple(overrides),
    )
