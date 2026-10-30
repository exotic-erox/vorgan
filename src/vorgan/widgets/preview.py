"""Preview builders (pure functions, run in worker threads) and the preview pane."""
from __future__ import annotations

import io
import os
import time
from pathlib import Path

from rich.console import Group
from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from .. import archive
from ..model import ICONS_NERD, ICONS_PLAIN, TAGS, Entry, Loc, human_size, sort_entries
from ..theme import Palette, mix


def _cell_px() -> tuple[int, int]:
    """Terminal cell size in pixels (TIOCGWINSZ, foot reports it), else 8x16."""
    try:
        import fcntl
        import struct
        import termios
        r, c, xp, yp = struct.unpack("HHHH", fcntl.ioctl(1, termios.TIOCGWINSZ, b"\0" * 8))
        if r > 0 and c > 0 and xp > 0 and yp > 0:
            return max(4, xp // c), max(4, yp // r)
    except (OSError, ValueError):
        pass
    return 8, 16


def halfblock(img, cols: int, rows: int, bg: str, cell: tuple[int, int] = (8, 16)) -> Text:
    """Paint the image on the real pixel grid: each cell is filled from the
    average of the two pixel rectangles it covers, so the blocky '▀' grid
    matches the terminal's actual cell size instead of guessing."""
    from PIL import Image
    from rich.color import Color
    cw, ch = cell
    cols, rows = max(2, cols), max(1, rows)
    nw, nh = cols * cw, rows * 2 * ch               # full width, 2 px bands per cell
    img = img.convert("RGBA")
    base = Image.new("RGBA", (nw, nh), tuple(int(bg[i:i + 2], 16) for i in (1, 3, 5)) + (255,))
    base.alpha_composite(img.resize((nw, nh), Image.LANCZOS))
    px = base.convert("RGB").load()
    n = cw * ch

    def avg(x0: int, y0: int) -> tuple[int, int, int]:
        r = g = b = 0
        for yy in range(y0, y0 + ch):
            for xx in range(x0, x0 + cw):
                p = px[xx, yy]
                r += p[0]
                g += p[1]
                b += p[2]
        return r // n, g // n, b // n

    cache: dict = {}
    lines = []
    for cy in range(rows):
        t = Text(no_wrap=True, overflow="crop")
        for cx in range(cols):
            k = (avg(cx * cw, cy * 2 * ch), avg(cx * cw, cy * 2 * ch + ch))
            st = cache.get(k)
            if st is None:
                st = cache[k] = Style(color=Color.from_rgb(*k[0]), bgcolor=Color.from_rgb(*k[1]))
            t.append("▀", st)
        lines.append(t)
    return Text("\n").join(lines)


def _meta(rows: list[tuple[str, str]], pal: Palette) -> Text:
    t = Text()
    for k, v in rows:
        t.append(f"{k:<10}", Style(color=pal.faint))
        t.append(v + "\n", Style(color=pal.text))
    return t


def _header(e: Entry, pal: Palette, nerd: bool) -> Text:
    icon = (ICONS_NERD if nerd else ICONS_PLAIN)[e.kind]
    t = Text()
    t.append(f"{icon} ", Style(color=pal.kinds[e.kind]))
    t.append(e.name + "\n", Style(color=pal.text, bold=True))
    return t


def _listing(entries: list[Entry], pal: Palette, nerd: bool, limit: int = 60) -> Text:
    t = Text()
    ic = ICONS_NERD if nerd else ICONS_PLAIN
    es = sort_entries(entries)
    for e in es[:limit]:
        t.append(f"{ic[e.kind]} ", Style(color=pal.kinds[e.kind]))
        t.append(e.name + ("\n" if e.is_dir else ""), Style(color=pal.kinds["dir"] if e.is_dir else pal.dim, bold=e.is_dir))
        if not e.is_dir:
            t.append(f"  {human_size(e.size)}\n", Style(color=pal.faint))
    if len(es) > limit:
        t.append(f"… and {len(es) - limit} more\n", Style(color=pal.faint))
    if not es:
        t.append("(empty)\n", Style(color=pal.faint))
    return t


def _text_preview(data: bytes, name: str, pal: Palette, width: int) -> Group | Text:
    if b"\0" in data[:4096]:
        return Text("binary file", Style(color=pal.faint))
    code = data.decode("utf-8", "replace")
    lines = code.splitlines()[:200]
    code = "\n".join(lines)
    try:
        lex = Syntax.guess_lexer(name, code)
        return Syntax(code, lex, theme="ansi_dark" if pal.dark else "ansi_light", line_numbers=True,
                      word_wrap=False, background_color=pal.panel, indent_guides=False)
    except Exception:
        return Text(code, Style(color=pal.text))


def build_preview(e: Entry | None, loc: Loc, pal: Palette, cols: int, rows: int, nerd: bool = True,
                  passphrase: str | None = None, cell: tuple[int, int] = (8, 16)):
    """Return a Rich renderable describing the entry."""
    if e is None:
        return Text("nothing selected", Style(color=pal.faint))
    head = _header(e, pal, nerd)
    kind = e.kind
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e.mtime)) if e.mtime else "unknown"
    meta = [("type", TAGS[kind]), ("size", human_size(e.size) if not e.is_dir else "folder"), ("modified", when)]
    if e.perms:
        meta.append(("perms", e.perms))
    try:
        if e.virtual and e.is_dir:
            kids = archive.get_index(e.arc, passphrase).children(e.inner)
            return Group(head, _listing(kids, pal, nerd))
        if e.is_dir:
            from .. import fsops
            return Group(head, _listing(fsops.list_real(e.path), pal, nerd))
        if kind == "archive" and not e.virtual:
            idx = archive.get_index(e.path, passphrase)
            info = [("files", str(idx.count)), ("unpacked", human_size(idx.total))]
            return Group(head, _meta(meta + info, pal), Text("\n"), _listing(idx.children(""), pal, nerd))
        data = None
        if e.virtual:
            data = archive.read_member(e.arc, e.inner, 262144 if kind != "image" else 20_000_000, passphrase)
        if kind == "image":
            from PIL import Image
            src = io.BytesIO(data) if data is not None else e.path
            with Image.open(src) as im:
                dims = f"{im.width}×{im.height}"
                im.load()
                art = halfblock(im, max(8, cols), max(4, rows - 6), pal.soft, cell)
            return Group(head, art, Text("\n"), _meta(meta + [("pixels", dims)], pal))
        if kind in ("code", "text", "config", "other", "pdf") and kind != "pdf":
            if data is None:
                with open(e.path, "rb") as f:
                    data = f.read(65536)
            return Group(head, _meta(meta, pal), Text("\n"), _text_preview(data, e.name, pal, cols))
        return Group(head, _meta(meta, pal))
    except (OSError, archive.ArchiveError) as ex:
        t = Text(str(ex), Style(color=pal.err))
        if isinstance(ex, archive.ArchiveError) and ex.need_password:
            t = Text("password protected archive (press e to extract with a password)", Style(color=pal.pin))
        return Group(head, t)
    except Exception as ex:  # corrupt image, odd encodings, etc.
        return Group(head, _meta(meta, pal), Text(f"\npreview failed: {ex}", Style(color=pal.faint)))


class PreviewPane(VerticalScroll):
    DEFAULT_CSS = "PreviewPane { padding: 1 2; }"
    can_focus = False

    def compose(self):
        yield Static("", id="pv")

    last = None

    def set(self, renderable) -> None:
        self.last = renderable
        self.query_one("#pv", Static).update(renderable)
        self.scroll_home(animate=False)
