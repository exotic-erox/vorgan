"""Virtualised file list with full mouse support."""
from __future__ import annotations

import time

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip

from ..model import ICONS_NERD, ICONS_PLAIN, TAGS, Entry, human_size
from ..theme import mix

HINT_KEYS = "asdfghjklqwertyuiop"


def make_tags(n: int) -> list[str]:
    if n <= len(HINT_KEYS):
        return list(HINT_KEYS[:n])
    base = "asdfghjkl"
    return [a + b for a in base for b in base][:n]


def _fit(s: str, w: int) -> str:
    if w <= 0:
        return ""
    if cell_len(s) <= w:
        return s + " " * (w - cell_len(s))
    out = ""
    for ch in s:
        if cell_len(out + ch) > w - 1:
            break
        out += ch
    return out + "…" + " " * max(0, w - cell_len(out) - 1)


class FileList(ScrollView):
    can_focus = False

    def __init__(self, role: str = "main", **kw):
        super().__init__(**kw)
        self.role = role
        self.view: list[Entry] = []
        self.cursor = 0
        self.selected: set[str] = set()
        self.hints: dict[int, str] | None = None
        self.current_name: str | None = None
        self.drop_row: int | None = None
        self.hover_row: int | None = None
        self._down = None
        self._drag = False

    # ----- data -----
    def set_entries(self, entries: list[Entry], keep: str | None = None) -> None:
        self.view = entries
        self.selected &= {e.name for e in entries}
        self.virtual_size = Size(self.size.width, len(entries))
        if keep is not None:
            for i, e in enumerate(entries):
                if e.name == keep:
                    self.cursor = i
                    break
        self.cursor = max(0, min(self.cursor, len(entries) - 1))
        self.refresh()
        self.ensure_visible()

    def entry(self) -> Entry | None:
        return self.view[self.cursor] if 0 <= self.cursor < len(self.view) else None

    def ensure_visible(self) -> None:
        if self.view and self.size.height:
            top = int(self.scroll_offset.y)
            h = self.size.height
            if self.cursor < top:
                self.scroll_to(y=self.cursor, animate=False)
            elif self.cursor >= top + h:
                self.scroll_to(y=self.cursor - h + 1, animate=False)

    def on_resize(self, e: events.Resize) -> None:
        self.virtual_size = Size(e.size.width, len(self.view))

    def row_at(self, y: int) -> int | None:
        r = y + int(self.scroll_offset.y)
        return r if 0 <= r < len(self.view) else None

    # ----- drawing -----
    def render_line(self, y: int) -> Strip:
        pal = self.app.pal
        w = self.size.width
        row = y + int(self.scroll_offset.y)
        base = pal.side if self.role == "parent" else pal.panel
        if row >= len(self.view):
            return Strip([Segment(" " * w, Style(bgcolor=base))], w)
        e = self.view[row]
        main = self.role == "main"
        is_cur = main and row == self.cursor
        is_sel = e.name in self.selected
        bg = base
        if self.role == "parent" and e.name == self.current_name:
            bg = mix(base, pal.accent, 0.12)
        if is_sel:
            bg = mix(base, pal.sel, 0.55)
        if is_cur:
            bg = pal.sel
        elif row == self.hover_row:
            bg = mix(bg, pal.text, 0.06)
        if row == self.drop_row:
            bg = mix(base, pal.pin, 0.35)
        S = lambda fg, **k: Style(color=fg, bgcolor=bg, **k)
        nerd = self.app.cfg.get("icons") == "nerd"
        icon = (ICONS_NERD if nerd else ICONS_PLAIN)[e.kind]
        right = ""
        if main and w >= 34:
            right += f" {TAGS[e.kind]} "
        if not e.is_dir:
            right += f"{human_size(e.size):>6} "
        elif main and w >= 34:
            right += "       "
        if main and w >= 70 and e.mtime:
            right = time.strftime(" %b %d", time.localtime(e.mtime)) + " " + right
        tag = self.hints.get(row) if self.hints else None
        segs = [Segment(" ", S(pal.accent) if is_cur else Style(bgcolor=bg))]
        if tag:
            segs.append(Segment(f"{tag:<2}", Style(color=pal.bg, bgcolor=pal.accent, bold=True)))
        else:
            segs.append(Segment(icon + " ", S(pal.kinds[e.kind])))
        name_w = w - 2 - cell_len(right)
        namestyle = S(pal.kinds["dir"] if e.is_dir else pal.text, bold=is_cur, italic=e.link)
        segs.append(Segment(_fit(e.name, name_w), namestyle))
        if right:
            segs.append(Segment(right, S(pal.faint if not is_cur else pal.dim)))
        strip = Strip(segs)
        return strip.adjust_cell_length(w, Style(bgcolor=bg))

    # ----- mouse -----
    def on_mouse_down(self, e: events.MouseDown) -> None:
        row = self.row_at(e.y)
        if e.button == 3:
            self.app.on_list_context(self, row, e)
            e.stop()
            return
        if e.button != 1:
            return
        self._down = (e.screen_x, e.screen_y, row, e.ctrl, e.shift)
        self._drag = False
        self.capture_mouse()

    def on_mouse_move(self, e: events.MouseMove) -> None:
        row = self.row_at(e.y)
        if self._down:
            sx, sy, srow, _, _ = self._down
            if not self._drag and srow is not None and self.role == "main" and abs(e.screen_x - sx) + abs(e.screen_y - sy) >= 3:
                self._drag = True
                self.app.drag_start(self, srow)
            if self._drag:
                self.app.drag_move(e.screen_x, e.screen_y)
            return
        if row != self.hover_row:
            self.hover_row = row
            self.refresh()

    def on_leave(self, e) -> None:
        if self.hover_row is not None and not self._down:
            self.hover_row = None
            self.refresh()

    def on_mouse_up(self, e: events.MouseUp) -> None:
        if not self._down:
            return
        self.release_mouse()
        _, _, row, ctrl, shift = self._down
        was_drag = self._drag
        self._down, self._drag = None, False
        if was_drag:
            self.app.drag_drop(e.screen_x, e.screen_y, e.ctrl)
        else:
            self.app.on_list_click(self, row, ctrl, shift)
