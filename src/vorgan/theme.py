"""Caelestia colour scheme reader and Palette."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

SCHEME_PATH = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "caelestia" / "scheme.json"


def _hex(v: str, default: str) -> str:
    v = (v or "").strip().lstrip("#")
    if len(v) == 6 and all(c in "0123456789abcdefABCDEF" for c in v):
        return "#" + v.lower()
    return default


def mix(a: str, b: str, t: float) -> str:
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    return "#%02x%02x%02x" % (round(ar + (br - ar) * t), round(ag + (bg - ag) * t), round(ab + (bb - ab) * t))


@dataclass
class Palette:
    bg: str = "#0d0e12"
    panel: str = "#121318"
    panel2: str = "#17191f"
    panel3: str = "#1d1f26"
    sel: str = "#445274"
    accent: str = "#b8c6ee"
    accent2: str = "#c0c6dc"
    text: str = "#e4e5f0"
    dim: str = "#a9aab5"
    faint: str = "#73757f"
    line: str = "#454850"
    err: str = "#fa746f"
    ok: str = "#b5ccba"
    pin: str = "#ffd866"
    dark: bool = True
    kinds: dict = field(default_factory=lambda: {
        "dir": "#8eadd5", "archive": "#dec5f5", "image": "#44def5", "audio": "#a99cff",
        "video": "#bbb9f8", "code": "#89ecff", "pdf": "#fa746f", "text": "#e4e5f0",
        "config": "#ffdcf2", "other": "#a9aab5",
    })

    @classmethod
    def from_scheme(cls, data: dict) -> "Palette":
        c = data.get("colours", {})
        d = cls()
        g = lambda k, dv: _hex(c.get(k, ""), dv)
        p = cls(
            bg=g("surface", d.bg), panel=g("surfaceContainerLow", d.panel), panel2=g("surfaceContainer", d.panel2),
            panel3=g("surfaceContainerHigh", d.panel3), sel=g("primaryContainer", d.sel), accent=g("primary", d.accent),
            accent2=g("secondary", d.accent2), text=g("onSurface", d.text), dim=g("onSurfaceVariant", d.dim),
            faint=g("outline", d.faint), line=g("outlineVariant", d.line), err=g("error", d.err), ok=g("success", d.ok),
            pin=g("term3", g("tertiary", d.pin)), dark=data.get("mode", "dark") != "light",
        )
        p.kinds = {
            "dir": g("sapphire", g("primary", d.kinds["dir"])), "archive": g("tertiary", d.kinds["archive"]),
            "image": g("term2", d.kinds["image"]), "audio": g("term1", d.kinds["audio"]),
            "video": g("term13", d.kinds["video"]), "code": g("term10", d.kinds["code"]),
            "pdf": g("error", d.kinds["pdf"]), "text": g("onSurface", d.kinds["text"]),
            "config": g("term3", d.kinds["config"]), "other": g("onSurfaceVariant", d.kinds["other"]),
        }
        return p

    def textual_vars(self) -> dict:
        return {
            "vg-bg": self.bg, "vg-panel": self.panel, "vg-panel2": self.panel2, "vg-panel3": self.panel3,
            "vg-side": self.side, "vg-soft": self.soft,
            "vg-sel": self.sel, "vg-accent": self.accent, "vg-text": self.text, "vg-dim": self.dim,
            "vg-faint": self.faint, "vg-line": self.line, "vg-err": self.err,
        }

    @property
    def side(self) -> str:
        """Dimmer surface for the side columns (mixed toward the background)."""
        return mix(self.panel, self.bg, 0.45)

    @property
    def soft(self) -> str:
        """Surface one step under the panel, for the preview."""
        return mix(self.panel, self.bg, 0.22)


def load_palette(path: Path | None = None) -> tuple[Palette, float]:
    """Return (palette, mtime). Falls back to the built-in dark palette."""
    p = path or SCHEME_PATH
    try:
        st = p.stat()
        return Palette.from_scheme(json.loads(p.read_text())), st.st_mtime
    except (OSError, ValueError, AttributeError):
        return Palette(), 0.0
