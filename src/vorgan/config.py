"""Config file (TOML) and small persisted state (pins, anchors)."""
from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

CONF_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "vorgan"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "vorgan"

DEFAULTS = {
    "icons": "nerd",            # nerd | plain
    "show_hidden": False,
    "sort": "name",             # name | size | date | type
    "archive_format": "zip",
    "graph_max_nodes": 28,
    "keys": {},                 # action = "key" overrides
}

KEYMAP = {
    "down": ["j", "down"], "up": ["k", "up"], "enter": ["l", "right", "enter"], "back": ["h", "left", "backspace"],
    "top": ["g", "home"], "bottom": ["G", "end"], "graph": ["tab"], "hint": ["f"], "search": ["/"],
    "hidden": ["."], "pin": ["m"], "warp": ["'"], "toggle": ["space"], "selall": ["ctrl+a"],
    "copy": ["y"], "cut": ["x"], "paste": ["p"], "rename": ["r", "f2"], "newdir": ["a", "f10"],
    "newfile": ["A"], "trash": ["d", "delete"], "delete": ["D", "shift+delete"], "extract": ["e"],
    "compress": ["z"], "quit_cd": ["q"], "quit": ["Q", "ctrl+q"], "help": ["?"], "sort": ["s"],
    "refresh": ["ctrl+r"], "frecent": ["~"], "terminal": ["t"], "clear": ["escape"],
}


def load_config() -> dict:
    cfg = {**DEFAULTS, "keys": {}}
    try:
        data = tomllib.loads((CONF_DIR / "config.toml").read_text())
        for k, v in data.items():
            if k in DEFAULTS and k != "keys":
                cfg[k] = v
        if isinstance(data.get("keys"), dict):
            cfg["keys"] = data["keys"]
    except (OSError, ValueError):
        pass
    return cfg


def build_keymap(cfg: dict) -> dict[str, str]:
    km: dict[str, list[str]] = {a: list(ks) for a, ks in KEYMAP.items()}
    for action, key in cfg.get("keys", {}).items():
        if action in km:
            km[action] = [key] if isinstance(key, str) else list(key)
    return {k: a for a, ks in km.items() for k in ks}


def _read(name: str) -> dict:
    try:
        return json.loads((STATE_DIR / name).read_text())
    except (OSError, ValueError):
        return {}


def _write(name: str, data: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_DIR / (name + ".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(STATE_DIR / name)
    except OSError:
        pass


class State:
    """Pins (graph) and anchors (letter bookmarks)."""

    def __init__(self) -> None:
        self.pins: dict[str, float] = {k: float(v) for k, v in _read("pins.json").items()}
        self.anchors: dict[str, str] = _read("anchors.json")
        self.cols = _read("cols.json")          # pane percentages after drag-resize

    def set_pin(self, path: str, radius: float) -> None:
        self.pins[path] = radius
        _write("pins.json", self.pins)

    def drop_pin(self, path: str) -> None:
        if self.pins.pop(path, None) is not None:
            _write("pins.json", self.pins)

    def set_anchor(self, letter: str, path: str) -> None:
        self.anchors[letter] = path
        _write("anchors.json", self.anchors)

    def set_cols(self, cols: dict) -> None:
        self.cols = {k: int(v) for k, v in cols.items() if v is not None}
        _write("cols.json", self.cols)
