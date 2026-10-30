"""Real file system operations. No UI code here."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from .model import Entry


def list_real(path: Path) -> list[Entry]:
    out: list[Entry] = []
    with os.scandir(path) as it:
        for de in it:
            try:
                st = de.stat(follow_symlinks=False)
                is_dir = de.is_dir()
            except OSError:
                continue
            out.append(Entry(de.name, is_dir, st.st_size, st.st_mtime, st.st_mode,
                             de.is_symlink(), path=Path(de.path)))
    return out


def list_subdirs(path: Path, show_hidden: bool = False) -> list[Path]:
    try:
        with os.scandir(path) as it:
            ds = [Path(d.path) for d in it if d.is_dir() and (show_hidden or not d.name.startswith("."))]
    except OSError:
        return []
    return sorted(ds, key=lambda p: p.name.lower())


def unique_path(folder: Path, name: str) -> Path:
    target = folder / name
    if not os.path.lexists(target):
        return target
    p = Path(name)
    suffix = "".join(p.suffixes[-2:]) if p.suffixes and p.suffixes[-2:-1] == [".tar"] else p.suffix
    stem = name[: len(name) - len(suffix)] if suffix else name
    k = 2
    while True:
        cand = folder / f"{stem} ({k}){suffix}"
        if not os.path.lexists(cand):
            return cand
        k += 1


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def copy_paths(srcs: list[Path], dst: Path) -> list[str]:
    errs: list[str] = []
    for s in srcs:
        try:
            if s.is_dir() and not s.is_symlink():
                if _inside(dst, s):
                    errs.append(f"{s.name}: cannot copy a folder into itself")
                    continue
                shutil.copytree(s, unique_path(dst, s.name), symlinks=True)
            else:
                shutil.copy2(s, unique_path(dst, s.name), follow_symlinks=False)
        except OSError as e:
            errs.append(f"{s.name}: {e.strerror or e}")
    return errs


def move_paths(srcs: list[Path], dst: Path) -> list[str]:
    errs: list[str] = []
    for s in srcs:
        try:
            if s.parent.resolve() == dst.resolve():
                continue
            if s.is_dir() and _inside(dst, s):
                errs.append(f"{s.name}: cannot move a folder into itself")
                continue
            shutil.move(str(s), str(unique_path(dst, s.name)))
        except (OSError, shutil.Error) as e:
            errs.append(f"{s.name}: {getattr(e, 'strerror', None) or e}")
    return errs


def _trash_fallback(p: Path) -> None:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "Trash"
    (base / "files").mkdir(parents=True, exist_ok=True)
    (base / "info").mkdir(parents=True, exist_ok=True)
    dest = unique_path(base / "files", p.name)
    info = base / "info" / (dest.name + ".trashinfo")
    info.write_text("[Trash Info]\nPath=%s\nDeletionDate=%s\n" % (p.resolve(), time.strftime("%Y-%m-%dT%H:%M:%S")))
    shutil.move(str(p), str(dest))


def trash_paths(paths: list[Path]) -> list[str]:
    errs: list[str] = []
    for p in paths:
        try:
            r = subprocess.run(["gio", "trash", "--", str(p)], capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                errs.append(f"{p.name}: {r.stderr.strip() or 'could not trash'}")
        except FileNotFoundError:
            try:
                _trash_fallback(p)
            except OSError as e:
                errs.append(f"{p.name}: {e.strerror or e}")
        except subprocess.TimeoutExpired:
            errs.append(f"{p.name}: trash timed out")
    return errs


def delete_paths(paths: list[Path]) -> list[str]:
    errs: list[str] = []
    for p in paths:
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError as e:
            errs.append(f"{p.name}: {e.strerror or e}")
    return errs


def rename_path(p: Path, new: str) -> str | None:
    new = new.strip()
    if not new or "/" in new:
        return "invalid name"
    t = p.with_name(new)
    if os.path.lexists(t):
        return f"{new} already exists"
    try:
        p.rename(t)
    except OSError as e:
        return e.strerror or str(e)
    return None


def make_dir(folder: Path, name: str) -> str | None:
    name = name.strip()
    if not name or "/" in name:
        return "invalid name"
    try:
        unique_path(folder, name).mkdir(parents=False)
    except OSError as e:
        return e.strerror or str(e)
    return None


def make_file(folder: Path, name: str) -> str | None:
    name = name.strip()
    if not name or "/" in name:
        return "invalid name"
    try:
        unique_path(folder, name).touch()
    except OSError as e:
        return e.strerror or str(e)
    return None
