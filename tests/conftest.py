import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A throwaway copy of the repo's inputs, goldens, sources and profiles."""
    for rel in ("legacy/LOANCALC.cbl", "profiles", "data/inputs", "data/golden", "data/manifests",
                "modern/java/src", "modern/java-naive/src", "docs"):
        src, dst = REPO / rel, tmp_path / rel
        if src.is_dir():
            shutil.copytree(src, dst)
        elif src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    monkeypatch.setenv("COBOLBRIDGE_ROOT", str(tmp_path))
    return tmp_path


def has_tool(name: str) -> bool:
    return shutil.which(name) is not None


needs_cobc = pytest.mark.skipif(not has_tool("cobc"), reason="GnuCOBOL not installed")
needs_java = pytest.mark.skipif(not has_tool("javac"), reason="JDK not installed")
