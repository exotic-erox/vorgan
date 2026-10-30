import os, sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def tree(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "conf"))
    import vorgan.config as cfg
    # the module resolved these dirs from the env at import time, so tests must
    # pin them here too or they quietly read the user's real state
    monkeypatch.setattr(cfg, "STATE_DIR", tmp_path / "state" / "vorgan")
    monkeypatch.setattr(cfg, "CONF_DIR", tmp_path / "conf" / "vorgan")
    root = tmp_path / "home"
    for d in ["Projects/orvix/src", "Projects/kolor", "Pictures", "Music", "Downloads", "Documents", ".config"]:
        (root / d).mkdir(parents=True)
    (root / "notes.md").write_text("# hello\nworld\n")
    (root / "todo.txt").write_text("buy coffee\n")
    (root / "Documents" / "a.txt").write_text("a")
    (root / "Documents" / "b.txt").write_text("b")
    (root / ".hidden").write_text("x")
    from PIL import Image
    Image.new("RGB", (64, 32), (200, 80, 120)).save(root / "Pictures" / "pic.png")
    return root
