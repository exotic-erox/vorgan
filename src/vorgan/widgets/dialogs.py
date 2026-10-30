"""Modal dialogs: forms, context menu, help."""
from __future__ import annotations

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from ..theme import mix


class Form(ModalScreen):
    """fields: dicts with id, label, kind (input|password|select|check), value, options."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    Form { align: center middle; background: rgba(0,0,0,0.55); }
    Form #box { width: 66; max-width: 96%; height: auto; padding: 1 2; background: $vg-panel2; border: round $vg-line; }
    Form #ftitle { text-style: bold; color: $vg-accent; margin-bottom: 1; }
    Form #fnote { color: $vg-dim; margin-bottom: 1; }
    Form .frow { height: auto; margin-bottom: 1; }
    Form .flabel { width: 16; padding-top: 1; color: $vg-dim; }
    Form Input { width: 1fr; }
    Form Select { width: 1fr; }
    Form #fbtns { height: auto; align-horizontal: right; margin-top: 1; }
    Form Button { margin-left: 2; min-width: 12; }
    """

    def __init__(self, title: str, fields: list[dict], ok: str = "OK", note: str = ""):
        super().__init__()
        self.title_, self.fields, self.ok_label, self.note = title, fields, ok, note

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static(self.title_, id="ftitle")
            if self.note:
                yield Static(self.note, id="fnote")
            for f in self.fields:
                with Horizontal(classes="frow"):
                    k = f.get("kind", "input")
                    if k != "check":
                        yield Label(f["label"], classes="flabel")
                    if k in ("input", "password"):
                        yield Input(value=str(f.get("value", "")), password=(k == "password"), id="f_" + f["id"])
                    elif k == "select":
                        yield Select([(o, o) for o in f["options"]], value=f.get("value", f["options"][0]), allow_blank=False, id="f_" + f["id"])
                    else:
                        yield Checkbox(f["label"], value=bool(f.get("value", False)), id="f_" + f["id"])
            with Horizontal(id="fbtns"):
                yield Button(self.ok_label, id="ok", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        for w in self.query(Input):
            w.focus()
            break

    def values(self) -> dict:
        out = {}
        for f in self.fields:
            w = self.query_one("#f_" + f["id"])
            out[f["id"]] = w.value
        return out

    def on_button_pressed(self, e: Button.Pressed) -> None:
        e.stop()
        self.dismiss(self.values() if e.button.id == "ok" else None)

    def on_input_submitted(self, e: Input.Submitted) -> None:
        e.stop()
        self.dismiss(self.values())

    def action_cancel(self) -> None:
        self.dismiss(None)


class MenuView(Widget):
    can_focus = False

    def __init__(self, items: list[tuple[str, str | None, bool]]):
        super().__init__(id="menu")
        self.items = items
        self.hover = -1
        self.w = max(cell_len(i[0]) for i in items if i[1] is not None) + 4
        self.styles.width = self.w + 2
        self.styles.height = len(items) + 2

    def render(self) -> Text:
        pal = self.app.pal
        out = Text(no_wrap=True, overflow="crop")
        for i, (label, aid, enabled) in enumerate(self.items):
            if aid is None:
                out.append("─" * self.w, Style(color=pal.line, bgcolor=pal.panel3))
            else:
                bg = pal.sel if i == self.hover and enabled else pal.panel3
                fg = pal.text if enabled else pal.faint
                out.append(f" {label}".ljust(self.w), Style(color=fg, bgcolor=bg))
            if i < len(self.items) - 1:
                out.append("\n")
        return out

    def _row(self, y: int) -> int:
        y -= 0
        return y if 0 <= y < len(self.items) and self.items[y][1] is not None else -1

    def on_mouse_move(self, e: events.MouseMove) -> None:
        h = self._row(e.y)
        if h != self.hover:
            self.hover = h
            self.refresh()

    def on_click(self, e: events.Click) -> None:
        e.stop()
        h = self._row(e.y)
        if h >= 0 and self.items[h][2]:
            self.screen.dismiss(self.items[h][1])


class MenuScreen(ModalScreen):
    BINDINGS = [Binding("escape", "close", "Close")]
    DEFAULT_CSS = """
    MenuScreen { background: rgba(0,0,0,0); align: left top; }
    MenuScreen #menu { background: $vg-panel3; border: round $vg-line; }
    """

    def __init__(self, items, x: int = 0, y: int = 0):
        super().__init__()
        self.items, self.x0, self.y0 = items, x, y

    def compose(self) -> ComposeResult:
        yield MenuView(self.items)

    def on_mount(self) -> None:
        m = self.query_one(MenuView)
        w, h = m.w + 2, len(self.items) + 2
        sw, sh = self.app.size
        m.styles.offset = (max(0, min(self.x0, sw - w)), max(0, min(self.y0, sh - h)))

    def on_click(self, e: events.Click) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


HELP = [
    ("Move", "j k / arrows · l Enter open · h Backspace up · g G top bottom"),
    ("Graph", "Tab opens the bubble graph · click bubble dive · drag to pin · right-click unpin"),
    ("Jump", "f hint tags · m + letter pin folder · apostrophe + letter warp · ~ frequent folders"),
    ("Find", "/ live filter · . hidden files · s sort"),
    ("Select", "space toggle · ctrl+a all · ctrl/shift click · drag onto folder to move"),
    ("Files", "y copy · x cut · p paste · r rename · a new folder · A new file · d trash · D delete"),
    ("Archives", "Enter browses inside · e extract (here or to a path) · z compress (name, format, path)"),
    ("Other", "t terminal here · ctrl+r refresh · q quit and cd · Q quit"),
]


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape", "close", "Close")]
    DEFAULT_CSS = """
    HelpScreen { align: center middle; background: rgba(0,0,0,0.6); }
    HelpScreen #hbox { width: 92; max-width: 98%; height: auto; padding: 1 2; background: $vg-panel2; border: round $vg-line; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="hbox"):
            yield Static("")

    def on_mount(self) -> None:
        pal = self.app.pal
        t = Text()
        t.append("Vorgan · keys and mouse\n\n", Style(color=pal.accent, bold=True))
        for k, v in HELP:
            t.append(f"{k:<9}", Style(color=pal.pin, bold=True))
            t.append(v + "\n", Style(color=pal.text))
        t.append("\nEvery action is also in the toolbar and the right-click menu. Esc or click to close.", Style(color=pal.dim))
        self.query_one(Static).update(t)

    def on_click(self, e) -> None:
        self.dismiss(None)

    def on_key(self, e: events.Key) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
