"""The Graph navigator: Obsidian-style bubbles of folders, fully mouse driven."""
from __future__ import annotations

import math

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Static

from ..graphcore import GNode, Graph
from ..model import Loc

TIP = "click a bubble to dive in · drag one near the centre to pin it · right-click unpins · wheel zooms"


class GraphView(Widget):
    DEFAULT_CSS = "GraphView { width: 1fr; height: 1fr; background: $vg-bg; }"
    can_focus = False

    def __init__(self, graph: Graph):
        super().__init__()
        self.g = graph
        self.hover: GNode | None = None
        self.focus_node: GNode | None = None
        self.drag: GNode | None = None
        self._down: tuple[GNode, float, float] | None = None
        self._moved = False
        self.awake = True
        self.idle = 0
        self.dirty = True
        self._text = Text("")

    def on_mount(self) -> None:
        self.set_interval(1 / 30, self._tick)

    def on_resize(self, e: events.Resize) -> None:
        self.g.set_size(e.size.width, e.size.height)
        self.wake()

    def wake(self) -> None:
        self.awake, self.idle, self.dirty = True, 0, True

    def _tick(self) -> None:
        if self.awake:
            e = self.g.step(self.drag)
            self.dirty = True
            if e < 0.12 * len(self.g.nodes) and not self.drag:
                self.idle += 1
                if self.idle > 10:
                    self.awake = False
            else:
                self.idle = 0
        if self.dirty and self.g.W:
            self._text = self.g.render(self.hover or self.focus_node)
            self.dirty = False
            self.refresh()

    def render(self) -> Text:
        return self._text

    # ---- helpers ----
    def _dots(self, e) -> tuple[float, float]:
        return e.x * 2 + 1, e.y * 4 + 2

    def _set_hover(self, n: GNode | None) -> None:
        if n is not self.hover:
            self.hover = n
            self.dirty = True
            if hasattr(self.screen, "set_info"):
                self.screen.set_info(n)

    # ---- mouse ----
    def on_mouse_move(self, e: events.MouseMove) -> None:
        dx, dy = self._dots(e)
        if self._down and not self._moved:
            node, sx, sy = self._down
            if node.role != "c" and math.hypot(dx - sx, dy - sy) > 6:
                self._moved, self.drag = True, node
        if self.drag:
            x, y = self.g.to_world(dx, dy)
            self.drag.x, self.drag.y, self.drag.vx, self.drag.vy = x, y, 0.0, 0.0
            self.wake()
            return
        self._set_hover(self.g.node_at(dx, dy))

    def on_mouse_down(self, e: events.MouseDown) -> None:
        dx, dy = self._dots(e)
        n = self.g.node_at(dx, dy)
        if e.button == 3:
            if n and self.g.unpin(n):
                self.app.notify(f"unpinned {n.name}", timeout=2)
                self.wake()
            return
        if e.button == 1 and n:
            self._down, self._moved = (n, dx, dy), False
            self.capture_mouse()

    def on_mouse_up(self, e: events.MouseUp) -> None:
        if not self._down:
            return
        self.release_mouse()
        node, _, _ = self._down
        self._down = None
        if self.drag:
            d, self.drag = self.drag, None
            if d.role == "k":
                self.g.pin(d)
                self.app.notify(f"pinned {d.name}", timeout=2)
            self.wake()
            return
        self.activate(node)

    def on_mouse_scroll_up(self, e: events.MouseScrollUp) -> None:
        self.zoom_by(1.12)

    def on_mouse_scroll_down(self, e: events.MouseScrollDown) -> None:
        self.zoom_by(1 / 1.12)

    def zoom_by(self, f: float) -> None:
        self.g.zoom = max(0.5, min(2.4, self.g.zoom * f))
        self.wake()

    # ---- actions ----
    def activate(self, node: GNode) -> None:
        if node.role == "c":
            self.screen.close_here()
            return
        self.g.dive(node)
        self.hover = self.focus_node = None
        if hasattr(self.screen, "refresh_title"):
            self.screen.refresh_title()
        self.wake()

    def cycle(self, d: int) -> None:
        ks = [n for n in self.g.nodes if n.role in ("k", "m")]
        if not ks:
            return
        ks.sort(key=lambda n: math.atan2(n.y, n.x))
        i = ks.index(self.focus_node) if self.focus_node in ks else (-1 if d > 0 else 0)
        self.focus_node = ks[(i + d) % len(ks)]
        self.dirty = True
        if hasattr(self.screen, "set_info"):
            self.screen.set_info(self.focus_node)


class GraphScreen(ModalScreen):
    BINDINGS = [Binding("tab", "close_here", "Go here", priority=True)]
    DEFAULT_CSS = """
    GraphScreen { background: $vg-bg; }
    GraphScreen #gtitle { height: 1; background: $vg-panel2; color: $vg-text; padding: 0 1; }
    GraphScreen #ginfo { height: 1; background: $vg-panel2; color: $vg-dim; padding: 0 1; }
    """

    def __init__(self, graph: Graph):
        super().__init__()
        self.g = graph

    def compose(self) -> ComposeResult:
        yield Static("", id="gtitle")
        yield GraphView(self.g)
        yield Static(TIP, id="ginfo")

    def on_mount(self) -> None:
        self.refresh_title()

    def refresh_title(self) -> None:
        pal = self.app.pal
        t = Text()
        t.append(" GRAPH ", Style(color=pal.bg, bgcolor=pal.accent, bold=True))
        t.append("  ")
        crumbs = self.g.loc.crumbs()
        crumbs = crumbs[-6:]
        for i, (name, _) in enumerate(crumbs):
            if i:
                t.append(" › ", Style(color=pal.faint))
            t.append(name, Style(color=pal.accent if i == len(crumbs) - 1 else pal.dim, bold=i == len(crumbs) - 1))
        if self.g.show_hidden:
            t.append("   hidden shown", Style(color=pal.pin))
        self.query_one("#gtitle", Static).update(t)
        self.set_info(None)

    def set_info(self, n: GNode | None) -> None:
        pal = self.app.pal
        t = Text()
        if n is None:
            t.append(TIP, Style(color=pal.dim))
            t.append("   esc go here · q cancel", Style(color=pal.faint))
        else:
            what = "click to close and go here" if n.role == "c" else "click for next page" if n.role == "m" else "click to go up" if n.role == "p" else "click to dive in"
            cnt = f" · {n.count} items" if n.role in ("c", "k") and not n.arc else ""
            t.append(f" {n.name}", Style(color=pal.accent, bold=True))
            t.append(f"{cnt} · {what}", Style(color=pal.dim))
            if n.key in self.g.state.pins:
                t.append(" · pinned (right-click to unpin)", Style(color=pal.pin))
        self.query_one("#ginfo", Static).update(t)

    def close_here(self) -> None:
        self.dismiss(self.g.loc)

    def action_close_here(self) -> None:
        self.close_here()

    def on_key(self, e: events.Key) -> None:
        v = self.query_one(GraphView)
        k = e.character if e.is_printable and e.character else e.key
        e.stop()
        if k in ("escape",):
            self.close_here()
        elif k == "enter":
            if v.focus_node and v.focus_node.role != "c":
                v.activate(v.focus_node)
            else:
                self.close_here()
        elif k in ("q",):
            self.dismiss(None)
        elif k in ("h", "backspace", "left"):
            if self.g.up():
                v.hover = v.focus_node = None
                self.refresh_title()
                v.wake()
        elif k in ("j", "down", "l", "right") and k in ("j", "down"):
            v.cycle(1)
        elif k in ("k", "up"):
            v.cycle(-1)
        elif k in ("l", "right", " "):
            if v.focus_node:
                v.activate(v.focus_node)
        elif k == ".":
            self.g.toggle_hidden()
            self.refresh_title()
            v.wake()
        elif k == "n":
            m = next((n for n in self.g.nodes if n.role == "m"), None)
            if m:
                v.activate(m)
        elif k == "r":
            self.g.reset_layout()
            v.wake()
        elif k in ("+", "="):
            v.zoom_by(1.15)
        elif k == "-":
            v.zoom_by(1 / 1.15)
        elif k == "0":
            self.g.zoom = 1.0
            v.wake()
