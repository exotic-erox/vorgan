"""Clickable bars (trail, toolbar)."""
from __future__ import annotations

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual import events
from textual.widget import Widget

from ..theme import mix


class Sizer(Widget):
    """A one-column handle: drag it with the mouse to resize the panes."""
    DEFAULT_CSS = "Sizer { width: 1; }"

    def __init__(self, pane: str, **kw):
        super().__init__(**kw)
        self.pane = pane
        self._drag = self._hov = False

    def render(self) -> Text:
        pal = self.app.pal
        fg = mix(pal.panel2, pal.accent, 0.6) if (self._drag or self._hov) else pal.faint
        body = "\n".join("│" for _ in range(max(1, self.size.height)))
        return Text(body, Style(color=fg, bgcolor=pal.panel2))

    def on_mouse_down(self, e: events.MouseDown) -> None:
        if e.button == 1:
            self._drag = True
            self._hov = True
            self.capture_mouse()
            self.app.resize_pane(self.pane, e.screen_x)

    def on_mouse_move(self, e: events.MouseMove) -> None:
        if self._drag:
            self.app.resize_pane(self.pane, e.screen_x)
        elif not self._hov:
            self._hov = True
            self.refresh()

    def on_mouse_up(self, e: events.MouseUp) -> None:
        if self._drag:
            self._drag = False
            self.release_mouse()
            self.app.save_panes()

    def on_leave(self, e) -> None:
        if self._hov and not self._drag:
            self._hov = False
            self.refresh()


class ClickBar(Widget):
    """A single row of clickable items. items: (label, action, kind, enabled)."""

    DEFAULT_CSS = "ClickBar { height: 1; }"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.items: list[tuple[str, str | None, str, bool]] = []
        self._spans: list[tuple[int, int, str]] = []
        self._hover = -1

    def set_items(self, items) -> None:
        self.items = items
        self.refresh()

    def render(self) -> Text:
        pal = self.app.pal
        bg = pal.panel2
        out = Text(no_wrap=True, overflow="crop")
        self._spans = []
        x = 0
        for i, (label, action, kind, enabled) in enumerate(self.items):
            if action is None:
                out.append(label, Style(color=pal.faint, bgcolor=bg))
                x += cell_len(label)
                continue
            hov = i == self._hover and enabled
            fg = pal.faint if not enabled else (pal.accent if kind in ("current", "accent") else pal.text)
            st = Style(color=fg, bold=kind == "current",
                       bgcolor=mix(bg, pal.accent, 0.16) if hov else (mix(bg, pal.accent, 0.10) if kind == "current" else bg))
            txt = f" {label} "
            out.append(txt, st)
            w = cell_len(txt)
            if enabled:
                self._spans.append((x, x + w, action))
            x += w
        return out

    def _at(self, x: int) -> int:
        pos = 0
        for i, (label, action, kind, enabled) in enumerate(self.items):
            w = cell_len(label) + (0 if action is None else 2)
            if pos <= x < pos + w:
                return i if action is not None else -1
            pos += w
        return -1

    def on_mouse_move(self, e: events.MouseMove) -> None:
        h = self._at(e.x)
        if h != self._hover:
            self._hover = h
            self.refresh()

    def on_leave(self, e) -> None:
        self._hover = -1
        self.refresh()

    def on_click(self, e: events.Click) -> None:
        for a, b, action in self._spans:
            if a <= e.x < b:
                self.app.bar_action(self.id or "", action)
                return
