"""Archives via bsdtar (libarchive). Archives behave like folders."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from .model import Entry, Loc

FORMATS = {
    "zip": ["--format", "zip"],
    "tar.gz": ["-z"],
    "tar.zst": ["--zstd"],
    "tar.xz": ["-J"],
    "7z": ["--format", "7zip"],
}
_ENV = {**os.environ, "LC_ALL": "C.UTF-8"}


class ArchiveError(Exception):
    def __init__(self, msg: str, need_password: bool = False):
        super().__init__(msg)
        self.need_password = need_password


def available() -> bool:
    return shutil.which("bsdtar") is not None


def _run(args: list[str], passphrase: str | None = None, timeout: int = 3600) -> subprocess.CompletedProcess:
    cmd = ["bsdtar", *args]
    if passphrase:
        cmd += ["--passphrase", passphrase]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=_ENV)
    except FileNotFoundError:
        raise ArchiveError("bsdtar is not installed (sudo pacman -S libarchive)")
    except subprocess.TimeoutExpired:
        raise ArchiveError("archive operation timed out")
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip()
        low = err.lower()
        raise ArchiveError(err.splitlines()[-1] if err else "archive error",
                           need_password=("passphrase" in low or "password" in low or "encrypted" in low))
    return r


def _parse_time(tokens: list[str]) -> float:
    try:
        s = " ".join(tokens)
        fmt = "%b %d %H:%M" if ":" in tokens[2] else "%b %d %Y"
        t = time.strptime(s, fmt)
        if ":" in tokens[2]:
            t = time.strptime(f"{time.localtime().tm_year} {s}", "%Y " + fmt)
        return time.mktime(t)
    except (ValueError, IndexError):
        return 0.0


def list_raw(arc: Path, passphrase: str | None = None) -> list[tuple[str, bool, int, float]]:
    r = _run(["-tvf", str(arc)], passphrase)
    out = []
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        perms, size, name = parts[0], parts[4], parts[8]
        if perms.startswith("h") and " link to " in name:
            continue
        if perms.startswith("l") and " -> " in name:
            name = name.split(" -> ")[0]
        try:
            sz = int(size)
        except ValueError:
            sz = 0
        out.append((name, perms.startswith("d") or name.endswith("/"), sz, _parse_time(parts[5:8])))
    return out


class ArcIndex:
    def __init__(self, arc: Path, raw: list[tuple[str, bool, int, float]]):
        self.arc = arc
        self.kids: dict[str, dict[str, Entry]] = {"": {}}
        self.count = 0
        self.total = 0
        for name, is_dir, size, mt in raw:
            p = name.strip("/")
            while p.startswith("./"):
                p = p[2:]
            if p in ("", "."):
                continue
            parts = p.split("/")
            for k in range(1, len(parts)):
                d = "/".join(parts[:k])
                parent = "/".join(parts[: k - 1])
                self.kids.setdefault(parent, {}).setdefault(parts[k - 1], Entry(
                    parts[k - 1], True, mtime=mt, mode=0o040755, arc=arc, inner=d))
                self.kids.setdefault(d, {})
            parent = "/".join(parts[:-1])
            slot = self.kids.setdefault(parent, {})
            if is_dir:
                slot[parts[-1]] = Entry(parts[-1], True, mtime=mt, mode=0o040755, arc=arc, inner=p)
                self.kids.setdefault(p, {})
            else:
                slot[parts[-1]] = Entry(parts[-1], False, size, mt, 0o100644, arc=arc, inner=p)
                self.count += 1
                self.total += size

    def children(self, inner: str) -> list[Entry]:
        return list(self.kids.get(inner.strip("/"), {}).values())


_CACHE: dict[tuple[str, float, int], ArcIndex] = {}


def get_index(arc: Path, passphrase: str | None = None) -> ArcIndex:
    st = arc.stat()
    key = (str(arc), st.st_mtime, st.st_size)
    idx = _CACHE.get(key)
    if idx is None:
        idx = ArcIndex(arc, list_raw(arc, passphrase))
        if len(_CACHE) > 8:
            _CACHE.clear()
        _CACHE[key] = idx
    return idx


def list_loc(loc: Loc, passphrase: str | None = None) -> list[Entry]:
    assert loc.arc is not None
    return get_index(loc.arc, passphrase).children(loc.inner)


def extract(arc: Path, dest: Path, members: list[str] | None = None, passphrase: str | None = None) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    args = ["-xf", str(arc), "-C", str(dest)]
    if members:
        args += members
    _run(args, passphrase)


def compress(out: Path, base: Path, names: list[str], fmt: str, passphrase: str | None = None) -> None:
    if fmt not in FORMATS:
        raise ArchiveError(f"unknown format {fmt}")
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["-c", *FORMATS[fmt], "-f", str(out), "-C", str(base)]
    if passphrase and fmt == "zip":
        args += ["--options", "zip:encryption=aes256"]
    elif passphrase:
        raise ArchiveError("passwords are only supported for zip here")
    args += ["--", *names]
    try:
        _run(args, passphrase if fmt == "zip" else None)
    except ArchiveError:
        try:
            out.unlink()
        except OSError:
            pass
        raise


def read_member(arc: Path, inner: str, limit: int = 262144, passphrase: str | None = None) -> bytes:
    cmd = ["bsdtar", "-xOf", str(arc)]
    if passphrase:
        cmd += ["--passphrase", passphrase]
    cmd += ["--", inner]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_ENV)
    except FileNotFoundError:
        raise ArchiveError("bsdtar is not installed")
    try:
        data = p.stdout.read(limit)
    finally:
        p.kill()
        p.wait()
    return data
