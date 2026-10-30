"""Data model: entries, locations, file kinds, icons. No UI code here."""
from __future__ import annotations

import stat as _stat
from dataclasses import dataclass
from pathlib import Path

ARC_EXTS = (
    ".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz",
    ".tar.zst", ".tzst", ".7z", ".rar", ".iso", ".cpio", ".jar", ".cbz", ".whl",
)
IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico"}
AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".opus", ".wav", ".m4a", ".aac"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
CODE_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".c", ".h", ".cpp", ".hpp", ".java",
    ".kt", ".lua", ".sh", ".fish", ".bash", ".zsh", ".html", ".css", ".scss", ".json",
    ".toml", ".yaml", ".yml", ".sql", ".php", ".rb", ".cs", ".vue", ".svelte",
}
TEXT_EXTS = {".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".ini", ".conf", ".cfg", ".env"}
CONFIG_NAMES = {"config", "hyprland.conf", ".gitconfig", ".bashrc", ".zshrc", "makefile", "dockerfile"}

TAGS = {
    "dir": "DIR", "archive": "ARC", "image": "IMG", "audio": "AUD", "video": "VID",
    "code": "SRC", "pdf": "PDF", "text": "TXT", "config": "CFG", "other": "---",
}
ICONS_NERD = {
    "dir": "\uf07b", "archive": "\uf1c6", "image": "\uf1c5", "audio": "\uf1c7", "video": "\uf1c8",
    "code": "\uf1c9", "pdf": "\uf1c1", "text": "\uf0f6", "config": "\uf013", "other": "\uf15b",
}
ICONS_PLAIN = {
    "dir": "▸", "archive": "▤", "image": "▣", "audio": "♪", "video": "▶",
    "code": "◆", "pdf": "▥", "text": "≡", "config": "⚙", "other": "·",
}


def is_archive_name(name: str) -> bool:
    return name.lower().endswith(ARC_EXTS)


def strip_arc_ext(name: str) -> str:
    low = name.lower()
    for e in sorted(ARC_EXTS, key=len, reverse=True):
        if low.endswith(e):
            return name[: -len(e)]
    return name


def kind_of(name: str, is_dir: bool) -> str:
    if is_dir:
        return "dir"
    low = name.lower()
    if low.endswith(ARC_EXTS):
        return "archive"
    ext = Path(low).suffix
    if ext in IMG_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    if ext == ".pdf":
        return "pdf"
    if low in CONFIG_NAMES:
        return "config"
    if ext in CODE_EXTS:
        return "code"
    if ext in TEXT_EXTS:
        return "text"
    return "other"


def human_size(n: int) -> str:
    x = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if x < 1024 or unit == "T":
            return f"{int(x)}{unit}" if unit == "B" or x >= 100 else f"{x:.1f}{unit}"
        x /= 1024
    return f"{n}B"


@dataclass(eq=False)
class Entry:
    name: str
    is_dir: bool
    size: int = 0
    mtime: float = 0.0
    mode: int = 0
    link: bool = False
    path: Path | None = None     # real file on disk
    arc: Path | None = None      # archive holding this entry (if virtual)
    inner: str = ""              # path inside that archive

    @property
    def kind(self) -> str:
        return kind_of(self.name, self.is_dir)

    @property
    def hidden(self) -> bool:
        return self.name.startswith(".")

    @property
    def virtual(self) -> bool:
        return self.arc is not None

    @property
    def perms(self) -> str:
        return _stat.filemode(self.mode) if self.mode else ""


@dataclass(frozen=True)
class Loc:
    """A place you can be: a real folder, or a folder inside an archive."""
    path: Path                    # real folder (for archives: the folder holding the archive)
    arc: Path | None = None
    inner: str = ""

    @property
    def in_arc(self) -> bool:
        return self.arc is not None

    def parent(self) -> "Loc | None":
        if self.arc:
            if self.inner:
                return Loc(self.path, self.arc, self.inner.rpartition("/")[0])
            return Loc(self.arc.parent)
        p = self.path.parent
        return Loc(p) if p != self.path else None

    def child(self, e: Entry) -> "Loc":
        if self.arc:
            return Loc(self.path, self.arc, e.inner)
        if e.kind == "archive":
            return Loc(self.path, e.path, "")
        return Loc(self.path / e.name)

    def crumbs(self) -> "list[tuple[str, Loc]]":
        out: list[tuple[str, Loc]] = []
        parts = self.path.parts
        for i, part in enumerate(parts):
            out.append((part if i else "/", Loc(Path(*parts[: i + 1]))))
        if self.arc:
            out.append((self.arc.name, Loc(self.path, self.arc, "")))
            acc = ""
            for seg in [s for s in self.inner.split("/") if s]:
                acc = f"{acc}/{seg}" if acc else seg
                out.append((seg, Loc(self.path, self.arc, acc)))
        return out

    def display(self) -> str:
        s = str(self.arc if self.arc else self.path)
        return s + (f"::{self.inner}" if self.arc and self.inner else "")


def sort_entries(entries: "list[Entry]", key: str = "name", reverse: bool = False) -> "list[Entry]":
    def k(e: Entry):
        if key == "size":
            return (not e.is_dir, -e.size, e.name.lower())
        if key == "date":
            return (not e.is_dir, -e.mtime, e.name.lower())
        if key == "type":
            return (not e.is_dir, e.kind, e.name.lower())
        return (not e.is_dir, e.name.lower())
    out = sorted(entries, key=k)
    if reverse:
        dirs = [e for e in out if e.is_dir][::-1]
        files = [e for e in out if not e.is_dir][::-1]
        return dirs + files
    return out


def fuzzy(name: str, q: str) -> bool:
    if not q:
        return True
    n, q = name.lower(), q.lower()
    if q in n:
        return True
    it = iter(n)
    return all(ch in it for ch in q)
