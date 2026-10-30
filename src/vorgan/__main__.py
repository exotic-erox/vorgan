"""Command line entry: vorgan [PATH] [--cwd-file FILE]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, archive


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vorgan", description="Vorgan: terminal file manager with the Graph navigator")
    ap.add_argument("path", nargs="?", default=".", help="folder (or file) to start in")
    ap.add_argument("--cwd-file", type=Path, help="write the final folder here when you quit with q (used by vg.fish)")
    ap.add_argument("--scheme", type=Path, help="Caelestia scheme.json to use instead of the default location")
    ap.add_argument("--version", action="version", version=f"vorgan {__version__}")
    a = ap.parse_args(argv)
    if not archive.available():
        print("note: bsdtar not found, archive features are off (sudo pacman -S libarchive)", file=sys.stderr)
    from .app import VorganApp
    app = VorganApp(Path(a.path), a.cwd_file, a.scheme)
    app.run()
    if a.cwd_file and app.final_cwd:
        try:
            a.cwd_file.write_text(app.final_cwd)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
