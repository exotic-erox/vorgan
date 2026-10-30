"""fish integration: final-folder handoff and frequent folders from history."""
from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

HISTORY = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "fish" / "fish_history"


def frecent_dirs(limit: int = 14, history: Path | None = None) -> list[Path]:
    """Most used folders, read from fish history (paths: entries and cd commands)."""
    try:
        text = (history or HISTORY).read_text(errors="replace")
    except OSError:
        return []
    counts: Counter[str] = Counter()
    in_paths = False
    for line in text.splitlines():
        if line.startswith("- cmd:"):
            in_paths = False
            m = re.match(r"- cmd: cd\s+(\S+)\s*$", line)
            if m:
                counts[os.path.expanduser(m.group(1))] += 1
        elif line.strip() == "paths:":
            in_paths = True
        elif in_paths and line.startswith("    - "):
            counts[os.path.expanduser(line.strip()[2:])] += 1
        elif not line.startswith(" "):
            in_paths = False
    out: list[Path] = []
    for p, _ in counts.most_common(limit * 4):
        pp = Path(p)
        d = pp if pp.is_dir() else pp.parent
        if d.is_dir() and d not in out and d != Path.home():
            out.append(d)
        if len(out) >= limit:
            break
    return out
