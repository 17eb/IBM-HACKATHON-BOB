"""Workspace-root path validation. Every file argument must resolve inside the root."""

from __future__ import annotations

import os
import re
from pathlib import Path

DATASET_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")
RUN_ID_RE = re.compile(r"^[a-z0-9_\-]{1,128}$")


class PathError(ValueError):
    """Raised when a caller-supplied path or identifier is not allowed."""


def workspace_root() -> Path:
    override = os.environ.get("COBOLBRIDGE_ROOT")
    base = Path(override) if override else Path(__file__).resolve().parent.parent
    return base.resolve()


def resolve_in_root(rel: str, root: Path | None = None, must_exist: bool = False) -> Path:
    """Resolve a workspace-relative path, rejecting absolute paths, '..' and symlink escapes."""
    root = (root or workspace_root()).resolve()
    if not isinstance(rel, str) or not rel.strip():
        raise PathError("path must be a non-empty workspace-relative string")
    candidate = Path(rel)
    if candidate.is_absolute() or rel.startswith(("~", "\\")):
        raise PathError(f"absolute paths are not allowed: {rel!r}")
    if ".." in candidate.parts:
        raise PathError(f"path traversal is not allowed: {rel!r}")
    full = (root / candidate).resolve()
    if not full.is_relative_to(root):
        raise PathError(f"path escapes the workspace root: {rel!r}")
    if must_exist and not full.exists():
        raise PathError(f"path does not exist: {rel!r}")
    return full


def check_dataset_id(dataset_id: str) -> str:
    if not isinstance(dataset_id, str) or not DATASET_ID_RE.match(dataset_id):
        raise PathError(f"invalid dataset_id {dataset_id!r}: use lowercase letters, digits and _")
    return dataset_id


def check_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        raise PathError(f"invalid run_id {run_id!r}")
    return run_id
