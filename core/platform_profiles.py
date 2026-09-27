"""Load declared provenance and record-format metadata for legacy fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from core.paths import PathError, check_dataset_id


def load_profile(root: Path, profile_id: str) -> dict:
    check_dataset_id(profile_id)
    path = root / "profiles" / f"{profile_id}.json"
    if not path.is_file():
        raise PathError(f"unknown profile {profile_id!r}")
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PathError(f"invalid profile {profile_id!r}: {exc}") from exc
    if not isinstance(profile, dict):
        raise PathError(f"profile {profile_id!r} must be an object")
    if profile.get("profile_id", profile_id) != profile_id:
        raise PathError(f"profile_id in {path.name} must be {profile_id!r}")
    missing = [key for key in ("system", "encoding", "record_format", "golden_origin")
               if not isinstance(profile.get(key), str) or not profile[key]]
    if missing:
        raise PathError(f"profile {profile_id!r} is missing required metadata: {missing}")
    return profile
