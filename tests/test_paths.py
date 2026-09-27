import os

import pytest

from core.paths import PathError, check_dataset_id, resolve_in_root


@pytest.mark.parametrize("bad", ["/etc/passwd", "../x", "data/../../x", "~/x", ""])
def test_rejects_unsafe_paths(tmp_path, bad):
    with pytest.raises(PathError):
        resolve_in_root(bad, tmp_path)


def test_rejects_symlink_escape(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    try:
        os.symlink(outside, tmp_path / "link.cbl")
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise
    with pytest.raises(PathError):
        resolve_in_root("link.cbl", tmp_path)


def test_accepts_workspace_path(tmp_path):
    (tmp_path / "legacy").mkdir()
    assert resolve_in_root("legacy", tmp_path, must_exist=True) == (tmp_path / "legacy").resolve()


@pytest.mark.parametrize("bad", ["../ds", "DS01", "ds 01", "a" * 65])
def test_rejects_bad_dataset_ids(bad):
    with pytest.raises(PathError):
        check_dataset_id(bad)
