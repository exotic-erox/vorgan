"""Vorgan: the Textual application that ties everything together."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from functools import partial
from pathlib import Path

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.geometry import Offset
from textual.theme import Theme
from textual.widgets import Input, Static

from . import archive, fsops
from .config import State, build_keymap, load_config
from .graphcore import Graph
from .model import Entry, Loc, fuzzy, human_size, sort_entries, strip_arc_ext
from .shellx import frecent_dirs
from .theme import SCHEME_PATH, load_palette
from .widgets.chrome import ClickBar, Sizer
from .widgets.dialogs import Form, HelpScreen, MenuScreen
from .widgets.filelist import FileList, make_tags
from .widgets.graph import GraphScreen
from .widgets.preview import PreviewPane, build_preview, _cell_px

SORTS = ["name", "size", "date", "type"]


class SearchInput(Input):
    def on_key(self, e: events.Key) -> None:
        if e.key == "escape":
            e.stop()
            self.app.end_search(clear=True)


class VorganApp(App):
    ENABLE_COMMAND_PALETTE = False
    AUTO_FOCUS = ""
    BINDINGS = [Binding("tab", "graph", "Graph", priority=True, show=False)]
    CSS = """
    Screen { background: $vg-bg; }
    #top { height: 1; background: $vg-panel2; }
    #trail { width: 1fr; height: 1; background: $vg-panel2; }
    #q { width: 24; height: 1; border: none; padding: 0 1; background: $vg-panel3; color: $vg-text; }
    #q:focus { border: none; background: $vg-sel; }
    #q > .input--placeholder { color: $vg-faint; }
    #tools { height: 1; background: $vg-panel2; }
    #cols { height: 1fr; }
    #parent { width: 22%; min-width: 14; background: $vg-side; scrollbar-size-vertical: 1; }
    #main { width: 1fr; background: $vg-panel; scrollbar-size-vertical: 1; }
    #preview { width: 38%; min-width: 26; background: $vg-soft; }
    #status { height: 1; background: $vg-panel2; color: $vg-dim; }
    """

    def __init__(self, start: Path | None = None, cwd_file: Path | None = None, scheme: Path | None = None,
                 cfg: dict | None = None, state: State | None = None):
        self.cfg = cfg or load_config()
        self.keymap = build_keymap(self.cfg)
        self.state = state or State()
        self.scheme_path = scheme or SCHEME_PATH
        self.pal, self._pal_mtime = load_palette(self.scheme_path)
        super().__init__()
        self._theme_n = 0
        self._apply_theme()
        start = Path(start or Path.cwd()).expanduser()
        self._start_select: str | None = None
        if start.is_file():
            self._start_select, start = start.name, start.parent
        self.loc = Loc(start.resolve())
        self.cwd_file = cwd_file
        self.final_cwd: str | None = None
        self.entries: list[Entry] = []
        self.filter_text = ""
        self.show_hidden = bool(self.cfg["show_hidden"])
        self.sort_key = self.cfg["sort"] if self.cfg["sort"] in SORTS else "name"
        self.clip: tuple[str, list[Path]] | None = None
        self.hint: str | None = None
        self.pending: str | None = None
        self.msg = ""
        self.passwords: dict[str, str] = {}
        self._want: str | None = None
        self._loading = False
        self._dir_mtime = 0.0
        self._anchor: int | None = None
        self._last_click = (None, 0.0)
        self._pv_timer = None
        self._drag: list[Entry] = []
        self._drop = None
        self._crumb_locs: list[Loc] = []

    # ---------- theme ----------
    def get_theme_variable_defaults(self) -> dict:
        return {**super().get_theme_variable_defaults(), **self.pal.textual_vars()}

    def _apply_theme(self) -> None:
        self._theme_n += 1
        p = self.pal
        name = f"vorgan{self._theme_n}"
        self.register_theme(Theme(name=name, primary=p.accent, secondary=p.accent2, warning=p.pin, error=p.err,
                                  success=p.ok, accent=p.accent, foreground=p.text, background=p.bg, surface=p.panel,
                                  panel=p.panel2, dark=p.dark, variables=p.textual_vars()))
        self.theme = name

    # ---------- layout ----------
    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield ClickBar(id="trail")
            yield SearchInput(placeholder="/ filter", id="q")
        yield ClickBar(id="tools")
        with Horizontal(id="cols"):
            yield FileList("parent", id="parent")
            yield Sizer("parent", id="sz-parent")
            yield FileList("main", id="main")
            yield Sizer("preview", id="sz-preview")
            yield PreviewPane(id="preview")
        yield Static(id="status")

    def on_mount(self) -> None:
        self.main = self.query_one("#main", FileList)
        self.parent_list = self.query_one("#parent", FileList)
        self.preview = self.query_one("#preview", PreviewPane)
        self._pct = {"parent": None, "preview": None}
        if self.state.cols:
            for which, pct in self.state.cols.items():
                self._set_pane(which, int(pct))
        self.set_focus(None)
        self.set_interval(1.0, self._watch)
        self._want = self._start_select
        self.goto(self.loc, self._start_select)

    def on_resize(self, e: events.Resize) -> None:
        if hasattr(self, "main"):
            self._set_bars()
            self._status()

    # ---------- loading ----------
    def goto(self, loc: Loc, select: str | None = None) -> None:
        self.loc, self._want = loc, select
        self.filter_text = ""
        self.hint = self.pending = None
        q = self.query_one("#q", Input)
        if q.value:
            q.value = ""
        self.main.selected.clear()
        self.main.hints = None
        self._set_bars()
        self._load_async()

    def reload(self, keep: str | None = None) -> None:
        self._want = keep or (self.main.entry().name if self.main.entry() else None)
        self._load_async()

    def _load_async(self) -> None:
        self._loading = True
        self.run_worker(partial(self._load, self.loc, self.passwords.get(str(self.loc.arc))), thread=True,
                        exclusive=True, group="load")

    def _load(self, loc: Loc, pw: str | None) -> None:
        err = None
        entries: list[Entry] = []
        pents: list[Entry] = []
        try:
            entries = archive.list_loc(loc, pw) if loc.arc else fsops.list_real(loc.path)
            par = loc.parent()
            if par:
                try:
                    pents = [e for e in (archive.list_loc(par) if par.arc else fsops.list_real(par.path)) if e.is_dir]
                except (OSError, archive.ArchiveError):
                    pents = []
        except (OSError, archive.ArchiveError) as ex:
            err = ex
        self.call_from_thread(self._loaded, loc, entries, pents, err)

    def _loaded(self, loc: Loc, entries: list[Entry], pents: list[Entry], err) -> None:
        if loc != self.loc:
            return
        self._loading = False
        if err is not None:
            if isinstance(err, archive.ArchiveError) and err.need_password and loc.arc:
                self._ask_password(loc.arc, lambda: self.reload())
            else:
                self.notify(str(getattr(err, "strerror", None) or err), severity="error")
                par = loc.parent()
                if par and not loc.arc and not loc.path.exists():
                    self.goto(par)
            return
        self.entries = entries
        if not loc.arc:
            try:
                self._dir_mtime = loc.path.stat().st_mtime
            except OSError:
                pass
        cur = (loc.inner.rsplit("/", 1)[-1] if loc.inner else loc.arc.name) if loc.arc else loc.path.name
        self.parent_list.current_name = cur
        pv = sort_entries([e for e in pents if self.show_hidden or not e.hidden])
        self.parent_list.set_entries(pv, cur)
        self.refresh_view(self._want)
        self._want = None

    def refresh_view(self, keep: str | None = None) -> None:
        cur = keep or (self.main.entry().name if self.main.entry() else None)
        es = [e for e in self.entries if (self.show_hidden or not e.hidden) and fuzzy(e.name, self.filter_text)]
        self.main.set_entries(sort_entries(es, self.sort_key), cur)
        self._after_move()

    def _after_move(self) -> None:
        self.main.refresh()
        self._set_tools()
        self._status()
        if self._pv_timer:
            self._pv_timer.stop()
        self._pv_timer = self.set_timer(0.09, self._start_preview)

    # ---------- preview ----------
    def _start_preview(self) -> None:
        e = self.main.entry()
        pane = self.preview
        cols, rows = max(10, pane.size.width - 5), max(6, pane.size.height - 4)
        pw = self.passwords.get(str(e.arc or e.path)) if e else None
        self.run_worker(partial(self._pv_work, e, self.loc, self.pal, cols, rows, self.cfg["icons"] == "nerd",
                                pw, _cell_px()),
                        thread=True, exclusive=True, group="preview")

    def _pv_work(self, e, loc, pal, cols, rows, nerd, pw, cell) -> None:
        r = build_preview(e, loc, pal, cols, rows, nerd, pw, cell)
        self.call_from_thread(self._pv_done, e, r)

    def _pv_done(self, e, r) -> None:
        if e is self.main.entry():
            self.preview.set(r)

    # ---------- chrome ----------
    def _set_bars(self) -> None:
        crumbs = self.loc.crumbs()
        self._crumb_locs = [l for _, l in crumbs]
        width = max(10, self.query_one("#trail").size.width - 4)
        start = 0
        while start < len(crumbs) - 1 and sum(cell_len(n) + 5 for n, _ in crumbs[start:]) > width:
            start += 1
        items: list[tuple[str, str | None, str, bool]] = []
        if start:
            items.append(("…", None, "sep", False))
        for i in range(start, len(crumbs)):
            if i > start:
                items.append((" › ", None, "sep", False))
            last = i == len(crumbs) - 1
            items.append((crumbs[i][0], f"cd:{i}", "current" if last else "normal", True))
        self.query_one("#trail", ClickBar).set_items(items)
        self._set_tools()

    def _set_tools(self) -> None:
        if not hasattr(self, "main"):
            return
        ts = self.targets()
        real = bool(ts) and not self.loc.arc
        can_ex = bool(self.loc.arc) or (bool(ts) and all(t.kind == "archive" for t in ts))
        S = (" · ", None, "sep", False)
        self.query_one("#tools", ClickBar).set_items([
            ("Graph", "graph", "accent", True), ("Up", "back", "normal", self.loc.parent() is not None), S,
            ("Cut", "cut", "normal", real), ("Copy", "copy", "normal", real),
            ("Paste", "paste", "normal", self.clip is not None and not self.loc.arc), S,
            ("+ Folder", "newdir", "normal", not self.loc.arc), ("Rename", "rename", "normal", real),
            ("Trash", "trash", "normal", real), S,
            ("Extract", "extract", "normal", can_ex), ("Compress", "compress", "normal", real), S,
            ("Hidden", "hidden", "current" if self.show_hidden else "normal", True),
            ("Sort: " + self.sort_key, "sort", "normal", True), ("Help", "help", "normal", True),
        ])

    def _status(self) -> None:
        if not hasattr(self, "main"):
            return
        pal = self.pal
        mode = "HINT" if self.hint is not None else "PIN" if self.pending == "pin" else "WARP" if self.pending == "warp" else "NAV"
        left = Text(no_wrap=True, overflow="crop")
        left.append(f" {mode} ", Style(color=pal.bg, bgcolor=pal.accent, bold=True))
        n, sel = len(self.main.view), len(self.main.selected)
        info = f"  {n} items"
        if sel:
            info += f" · {sel} selected"
        if self.filter_text:
            info += f' · filter "{self.filter_text}"'
        if self.show_hidden:
            info += " · hidden shown"
        if self.clip:
            info += f" · clipboard: {len(self.clip[1])} {self.clip[0]}"
        left.append(info, Style(color=pal.dim))
        if self.msg:
            left.append("  " + self.msg, Style(color=pal.pin))
        right = "Tab graph · ? keys "
        w = self.size.width
        pad = max(1, w - cell_len(left.plain) - cell_len(right))
        left.append(" " * pad + right, Style(color=pal.faint))
        self.query_one("#status", Static).update(left)

    def bar_action(self, bar: str, action: str) -> None:
        if action.startswith("cd:"):
            self.goto(self._crumb_locs[int(action[3:])])
        else:
            self.do(action)

    # ---------- pane widths ----------
    def _set_pane(self, which: str, pct: int) -> None:
        pct = min(34 if which == "parent" else 55, max(8 if which == "parent" else 14, pct))
        self._pct[which] = pct
        (self.parent_list if which == "parent" else self.preview).styles.width = f"{pct}%"

    def resize_pane(self, which: str, x: int) -> None:
        w = self.size.width
        if w:
            self._set_pane(which, (x * 100 // w) if which == "parent" else ((w - x) * 100 // w))

    def save_panes(self) -> None:
        self.state.set_cols({k: p for k, p in self._pct.items() if p is not None})
        self.notify("column widths saved", timeout=2)

    # ---------- watching ----------
    def _watch(self) -> None:
        try:
            mt = self.scheme_path.stat().st_mtime
        except OSError:
            mt = 0.0
        if mt != self._pal_mtime:
            self.pal, self._pal_mtime = load_palette(self.scheme_path)
            self._apply_theme()
            for w in (self.main, self.parent_list, self.query_one("#trail"), self.query_one("#tools")):
                w.refresh()
            self._status()
        if not self.loc.arc and not self._loading:
            try:
                m = self.loc.path.stat().st_mtime
            except OSError:
                return
            if m != self._dir_mtime:
                self._dir_mtime = m
                self.reload()

    # ---------- keys ----------
    def check_action(self, action: str, parameters) -> bool | None:
        if action == "graph" and (len(self.screen_stack) > 1 or isinstance(self.focused, Input)):
            return False
        return True

    def action_graph(self) -> None:
        self.act_graph()

    def on_key(self, e: events.Key) -> None:
        if len(self.screen_stack) > 1 or isinstance(self.focused, Input):
            return
        k = e.character if (e.is_printable and e.character) else e.key
        if k == " ":
            k = "space"
        if self.hint is not None:
            e.stop()
            self._hint_key(k)
            return
        if self.pending:
            e.stop()
            self._pending_key(k)
            return
        act = self.keymap.get(k)
        if act:
            e.stop()
            self.do(act)

    def do(self, action: str) -> None:
        fn = getattr(self, "act_" + action, None)
        if fn:
            fn()

    def _hint_key(self, k: str) -> None:
        m = self.main
        if k == "escape" or not (len(k) == 1 and k.isalpha()) or not m.hints:
            self._end_hint()
            return
        self.hint += k.lower()
        hit = [r for r, t in m.hints.items() if t == self.hint]
        if hit:
            r = hit[0]
            self._end_hint()
            m.cursor = r
            m.ensure_visible()
            self._after_move()
            ent = m.entry()
            if ent and (ent.is_dir or ent.kind == "archive"):
                self.act_enter()
        elif not any(t.startswith(self.hint) for t in m.hints.values()):
            self._end_hint()
        else:
            self._status()

    def _end_hint(self) -> None:
        self.hint = None
        self.main.hints = None
        self.main.refresh()
        self._status()

    def _pending_key(self, k: str) -> None:
        what, self.pending = self.pending, None
        if len(k) == 1 and k.isalpha():
            if what == "pin":
                self.state.set_anchor(k, str(self.loc.path))
                self.notify(f"pinned {self.loc.path} as '{k}'", timeout=3)
            else:
                p = self.state.anchors.get(k)
                if p and Path(p).is_dir():
                    self.goto(Loc(Path(p)))
                else:
                    self.notify(f"no folder pinned as '{k}'", severity="warning", timeout=3)
        self._status()

    # ---------- selection helpers ----------
    def targets(self) -> list[Entry]:
        m = self.main
        if m.selected:
            return [e for e in m.view if e.name in m.selected]
        e = m.entry()
        return [e] if e else []

    def _real_targets(self) -> list[Entry]:
        return [e for e in self.targets() if not e.virtual]

    def move(self, d: int) -> None:
        m = self.main
        if not m.view:
            return
        m.cursor = max(0, min(len(m.view) - 1, m.cursor + d))
        m.ensure_visible()
        self._after_move()

    # ---------- actions: navigation ----------
    def act_down(self) -> None:
        self.move(1)

    def act_up(self) -> None:
        self.move(-1)

    def act_top(self) -> None:
        self.main.cursor = 0
        self.main.scroll_home(animate=False)
        self._after_move()

    def act_bottom(self) -> None:
        self.main.cursor = max(0, len(self.main.view) - 1)
        self.main.ensure_visible()
        self._after_move()

    def act_enter(self) -> None:
        e = self.main.entry()
        if not e:
            return
        if e.is_dir or (e.kind == "archive" and not e.virtual):
            self.goto(self.loc.child(e))
        elif e.virtual:
            self.notify("extract it first (press e)", timeout=3)
        else:
            self.open_external(e.path)

    def act_back(self) -> None:
        par = self.loc.parent()
        if par:
            l = self.loc
            name = (l.inner.rsplit("/", 1)[-1] if l.inner else l.arc.name) if l.arc else l.path.name
            self.goto(par, select=name)

    def act_graph(self) -> None:
        g = Graph(self.loc, self.state, self.pal, self.show_hidden, int(self.cfg["graph_max_nodes"]))
        self.push_screen(GraphScreen(g), lambda r: r is not None and self.goto(r))

    def act_hint(self) -> None:
        m = self.main
        if not m.view:
            return
        top = int(m.scroll_offset.y)
        rows = list(range(top, min(len(m.view), top + m.size.height)))
        m.hints = dict(zip(rows, make_tags(len(rows))))
        self.hint = ""
        m.refresh()
        self._status()

    def act_search(self) -> None:
        self.query_one("#q", Input).focus()

    def end_search(self, clear: bool = False) -> None:
        q = self.query_one("#q", Input)
        if clear and q.value:
            q.value = ""
        self.set_focus(None)

    def on_input_changed(self, e: Input.Changed) -> None:
        if e.input.id == "q" and e.value != self.filter_text:
            self.filter_text = e.value
            self.main.cursor = 0
            self.refresh_view()

    def on_input_submitted(self, e: Input.Submitted) -> None:
        if e.input.id == "q":
            self.set_focus(None)

    def act_hidden(self) -> None:
        self.show_hidden = not self.show_hidden
        self.reload()

    def act_sort(self) -> None:
        self.sort_key = SORTS[(SORTS.index(self.sort_key) + 1) % len(SORTS)]
        self.refresh_view()
        self.notify(f"sort by {self.sort_key}", timeout=2)

    def act_pin(self) -> None:
        self.pending = "pin"
        self._status()

    def act_warp(self) -> None:
        self.pending = "warp"
        self._status()

    def act_frecent(self) -> None:
        dirs = frecent_dirs()
        if not dirs:
            self.notify("no folder history found yet", timeout=3)
            return
        home = str(Path.home())
        items = [(str(d).replace(home, "~", 1), f"dir:{d}", True) for d in dirs]
        self.push_screen(MenuScreen(items, 4, 2), lambda a: a and self.goto(Loc(Path(a[4:]))))

    def act_refresh(self) -> None:
        self.reload()

    def act_clear(self) -> None:
        if self.main.selected:
            self.main.selected.clear()
            self.main.refresh()
            self._after_move()
        elif self.filter_text:
            self.end_search(clear=True)

    def act_help(self) -> None:
        self.push_screen(HelpScreen())

    def act_toggle(self) -> None:
        e = self.main.entry()
        if e:
            self.main.selected ^= {e.name}
            self.move(1)

    def act_selall(self) -> None:
        self.main.selected = {e.name for e in self.main.view}
        self.main.refresh()
        self._after_move()

    # ---------- actions: files ----------
    def open_external(self, p: Path) -> None:
        try:
            subprocess.Popen(["xdg-open", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError as ex:
            self.notify(f"cannot open: {ex}", severity="error")

    def act_terminal(self) -> None:
        term = os.environ.get("TERMINAL", "foot")
        d = str(self.loc.path)
        args = ["-D", d] if "foot" in term else ["--working-directory", d]
        try:
            subprocess.Popen([term, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as ex:
            self.notify(f"cannot start {term}: {ex}", severity="error")

    def act_copy_path(self) -> None:
        e = self.main.entry()
        p = str(e.path) if e and e.path else str(self.loc.path)
        if shutil.which("wl-copy"):
            subprocess.run(["wl-copy", p])
        self.notify(p, timeout=4)

    def _clip_set(self, mode: str) -> None:
        ts = self._real_targets()
        if not ts:
            self.notify("nothing to copy here (inside an archive use e to extract)", timeout=3)
            return
        self.clip = (mode, [e.path for e in ts])
        self.notify(f"{'copied' if mode == 'copy' else 'cut'} {len(ts)} item(s)", timeout=2)
        self._set_tools()
        self._status()

    def act_copy(self) -> None:
        self._clip_set("copy")

    def act_cut(self) -> None:
        self._clip_set("cut")

    def act_paste(self) -> None:
        if not self.clip:
            self.notify("clipboard is empty", timeout=2)
            return
        if self.loc.arc:
            self.notify("cannot paste inside an archive", timeout=3)
            return
        mode, paths = self.clip
        dest = self.loc.path
        if mode == "cut":
            self.clip = None
        fn = (lambda: fsops.move_paths(paths, dest)) if mode == "cut" else (lambda: fsops.copy_paths(paths, dest))
        self.bg(f"{'moving' if mode == 'cut' else 'copying'} {len(paths)} item(s)", fn,
                done=f"{'moved' if mode == 'cut' else 'copied'} {len(paths)} item(s)")

    def act_rename(self) -> None:
        e = self.main.entry()
        if not e or e.virtual:
            self.notify("cannot rename inside an archive", timeout=3)
            return

        def done(v):
            if v:
                err = fsops.rename_path(e.path, v["name"])
                self.notify(err, severity="error") if err else self.reload(v["name"].strip())

        self.push_screen(Form("Rename", [dict(id="name", label="New name", value=e.name)], "Rename"), done)

    def _make(self, what: str) -> None:
        if self.loc.arc:
            self.notify("archives are read-only here", timeout=3)
            return

        def done(v):
            if v:
                fn = fsops.make_dir if what == "dir" else fsops.make_file
                err = fn(self.loc.path, v["name"])
                self.notify(err, severity="error") if err else self.reload(v["name"].strip())

        self.push_screen(Form("New folder" if what == "dir" else "New file",
                              [dict(id="name", label="Name", value="New folder" if what == "dir" else "untitled.txt")],
                              "Create"), done)

    def act_newdir(self) -> None:
        self._make("dir")

    def act_newfile(self) -> None:
        self._make("file")

    def act_trash(self) -> None:
        ts = self._real_targets()
        if not ts:
            return
        paths = [e.path for e in ts]
        self.main.selected.clear()
        self.bg(f"moving {len(paths)} item(s) to trash", lambda: fsops.trash_paths(paths), done=f"moved {len(paths)} item(s) to trash")

    def act_delete(self) -> None:
        ts = self._real_targets()
        if not ts:
            return
        paths = [e.path for e in ts]

        def done(v):
            if v is not None:
                self.main.selected.clear()
                self.bg("deleting", lambda: fsops.delete_paths(paths), done=f"deleted {len(paths)} item(s)")

        names = ", ".join(e.name for e in ts[:4]) + ("…" if len(ts) > 4 else "")
        self.push_screen(Form("Delete permanently?", [], "Delete", note=f"This cannot be undone: {names}"), done)

    def act_props(self) -> None:
        e = self.main.entry()
        if not e:
            return
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e.mtime)) if e.mtime else "unknown"
        note = f"{e.name}\n\nkind: {e.kind}\nsize: {human_size(e.size)}\nmodified: {when}\npermissions: {e.perms}\nlocation: {self.loc.display()}"
        self.push_screen(Form("Properties", [], "Close", note=note), lambda v: None)

    # ---------- actions: archives ----------
    def _ask_password(self, arc: Path, retry) -> None:
        def done(v):
            if v and v["pw"]:
                self.passwords[str(arc)] = v["pw"]
                retry()

        self.push_screen(Form("Password required", [dict(id="pw", label="Password", kind="password")], "Unlock",
                              note=arc.name), done)

    def _extract_jobs(self) -> tuple[list[tuple[Path, list[str] | None]], bool] | None:
        if self.loc.arc:
            ts = [e for e in self.targets()] if self.main.selected else []
            members = [e.inner for e in ts] or None
            return [(self.loc.arc, members)], members is None
        ts = [e for e in self.targets() if e.kind == "archive" and not e.virtual]
        if not ts:
            return None
        return [(e.path, None) for e in ts], True

    def act_extract(self) -> None:
        job = self._extract_jobs()
        if not job:
            self.notify("select an archive first", timeout=3)
            return
        jobs, whole = job
        names = ", ".join(a.name for a, _ in jobs)

        def done(v):
            if v:
                dest = Path(os.path.expanduser(v["dest"]))
                if not dest.is_absolute():
                    dest = self.loc.path / dest
                self._run_extract(jobs, dest, bool(v["sub"]) and whole, bool(v["go"]))

        self.push_screen(Form("Extract", [
            dict(id="dest", label="Extract to", value=str(self.loc.path)),
            dict(id="sub", label="Create a subfolder named after the archive", kind="check", value=whole),
            dict(id="go", label="Open the destination afterwards", kind="check", value=False),
        ], "Extract", note=names + ("" if whole else "  (selected items only)")), done)

    def act_extract_here(self) -> None:
        job = self._extract_jobs()
        if job:
            jobs, whole = job
            self._run_extract(jobs, self.loc.path, whole, False)

    def _run_extract(self, jobs, dest: Path, sub: bool, go: bool) -> None:
        def work():
            last = dest
            for arc, members in jobs:
                d = fsops.unique_path(dest, strip_arc_ext(arc.name)) if sub else dest
                archive.extract(arc, d, members, self.passwords.get(str(arc)))
                last = d
            return None

        def retry():
            self._run_extract(jobs, dest, sub, go)

        self.bg(f"extracting {len(jobs)} archive(s)", work, done=f"extracted to {dest}", retry=retry,
                retry_arc=jobs[0][0], after=(lambda: self.goto(Loc(dest))) if go else None)

    def act_compress(self) -> None:
        ts = self._real_targets()
        if not ts:
            self.notify("select files to compress first", timeout=3)
            return
        base = self.loc.path
        default = ts[0].name if ts[0].is_dir else Path(ts[0].name).stem
        if len(ts) > 1:
            default = base.name or "archive"
        fmts = list(archive.FORMATS)
        fmt0 = self.cfg["archive_format"] if self.cfg["archive_format"] in fmts else "zip"

        def done(v):
            if not v:
                return
            fmt = v["fmt"]
            dest = Path(os.path.expanduser(v["dest"]))
            if not dest.is_absolute():
                dest = base / dest
            self._run_compress(base, [e.name for e in ts], dest, v["name"].strip() or "archive", fmt, v["pw"] or None, bool(v["rm"]))

        self.push_screen(Form("Compress", [
            dict(id="name", label="Archive name", value=default),
            dict(id="fmt", label="Format", kind="select", options=fmts, value=fmt0),
            dict(id="dest", label="Save to", value=str(base)),
            dict(id="pw", label="Password (zip)", kind="password"),
            dict(id="rm", label="Move the originals to trash afterwards", kind="check", value=False),
        ], "Compress", note=f"{len(ts)} item(s): " + ", ".join(e.name for e in ts[:3]) + ("…" if len(ts) > 3 else "")), done)

    def act_compress_here(self) -> None:
        ts = self._real_targets()
        if ts:
            default = ts[0].name if (len(ts) == 1 and ts[0].is_dir) else (Path(ts[0].name).stem if len(ts) == 1 else (self.loc.path.name or "archive"))
            self._run_compress(self.loc.path, [e.name for e in ts], self.loc.path, default, "zip", None, False)

    def _run_compress(self, base: Path, names: list[str], dest: Path, name: str, fmt: str, pw: str | None, rm: bool) -> None:
        out = fsops.unique_path(dest, f"{name}.{fmt}")

        def work():
            archive.compress(out, base, names, fmt, pw)
            if rm:
                return fsops.trash_paths([base / n for n in names])
            return None

        self.main.selected.clear()
        self.bg(f"compressing to {out.name}", work, done=f"created {out.name}", select=out.name)

    # ---------- background ops ----------
    def bg(self, label: str, fn, done: str | None = None, select: str | None = None, retry=None,
           retry_arc: Path | None = None, after=None) -> None:
        self.msg = f"⏳ {label}…"
        self._status()

        def run():
            try:
                r = fn()
            except Exception as ex:  # reported to the user, never crashes the UI
                r = ex
            self.call_from_thread(self._bg_done, r, done, select, retry, retry_arc, after)

        self.run_worker(run, thread=True, group="ops")

    def _bg_done(self, r, done, select, retry, retry_arc, after) -> None:
        self.msg = ""
        if isinstance(r, archive.ArchiveError) and r.need_password and retry and retry_arc:
            self._ask_password(retry_arc, retry)
        elif isinstance(r, Exception):
            self.notify(str(getattr(r, "strerror", None) or r), severity="error", timeout=6)
        elif r:
            self.notify("; ".join(r[:3]), severity="warning", timeout=6)
        elif done:
            self.notify(done, timeout=3)
        if after and not isinstance(r, Exception):
            after()
        else:
            self.reload(select)
        self._set_tools()
        self._status()

    # ---------- mouse: lists ----------
    def on_list_click(self, lst: FileList, row: int | None, ctrl: bool, shift: bool) -> None:
        if lst.role == "parent":
            par = self.loc.parent()
            if row is not None and par and lst.view[row].is_dir:
                self.goto(par.child(lst.view[row]))
            return
        m = self.main
        if row is None:
            m.selected.clear()
            m.refresh()
            self._after_move()
            return
        e = m.view[row]
        now = time.monotonic()
        if ctrl:
            m.selected ^= {e.name}
            m.cursor, self._anchor = row, row
        elif shift:
            a = self._anchor if self._anchor is not None else m.cursor
            lo, hi = sorted((a, row))
            m.selected = {x.name for x in m.view[lo:hi + 1]}
            m.cursor = row
        else:
            lrow, lt = self._last_click
            if lrow == row and now - lt < 0.45:
                self._last_click = (None, 0.0)
                m.cursor = row
                self.act_enter()
                return
            self._last_click = (row, now)
            m.selected.clear()
            m.cursor, self._anchor = row, row
        m.refresh()
        self._after_move()

    def on_list_context(self, lst: FileList, row: int | None, ev) -> None:
        if lst.role != "main":
            return
        m = self.main
        arc = self.loc.arc is not None
        if row is not None:
            e = m.view[row]
            if e.name not in m.selected:
                m.selected.clear()
            m.cursor = row
            m.refresh()
            self._after_move()
            ts = self.targets()
            can_ex = arc or all(t.kind == "archive" and not t.virtual for t in ts)
            items = [("Open", "enter", True), None,
                     ("Cut", "cut", not arc), ("Copy", "copy", not arc), ("Paste", "paste", self.clip is not None and not arc), None,
                     ("Rename…", "rename", not arc), ("Move to Trash", "trash", not arc), None]
            if can_ex:
                items += [("Extract Here", "extract_here", True), ("Extract To…", "extract", True)]
            items += [("Compress Here (.zip)", "compress_here", not arc), ("Compress To…", "compress", not arc), None,
                      ("Copy Path", "copy_path", True), ("Open Terminal Here", "terminal", True), ("Properties", "props", True)]
        else:
            m.selected.clear()
            m.refresh()
            items = [("New Folder…", "newdir", not arc), ("New File…", "newfile", not arc),
                     ("Paste", "paste", self.clip is not None and not arc), None,
                     ("Hide Hidden Files" if self.show_hidden else "Show Hidden Files", "hidden", True),
                     (f"Sort by {SORTS[(SORTS.index(self.sort_key) + 1) % 4]}", "sort", True), None,
                     ("Open Terminal Here", "terminal", True), ("Open Graph", "graph", True)]
        items = [("", None, False) if i is None else i for i in items]
        self.push_screen(MenuScreen(items, ev.screen_x, ev.screen_y), lambda a: a and self.do(a))

    # ---------- mouse: drag and drop ----------
    def drag_start(self, lst: FileList, row: int) -> None:
        e = lst.view[row]
        names = lst.selected if e.name in lst.selected else {e.name}
        self._drag = [x for x in lst.view if x.name in names and not x.virtual]
        self._drop = None
        self.msg = f"dragging {len(self._drag)} item(s): drop on a folder (hold ctrl to copy)"
        self._status()

    def drag_move(self, x: int, y: int) -> None:
        for l in (self.main, self.parent_list):
            if l.drop_row is not None:
                l.drop_row = None
                l.refresh()
        self._drop = None
        try:
            w, _ = self.get_widget_at(x, y)
        except Exception:
            return
        if isinstance(w, FileList):
            row = w.row_at(y - w.region.y)
            if row is not None:
                t = w.view[row]
                if t.is_dir and not t.virtual and t not in self._drag and t.path:
                    w.drop_row = row
                    self._drop = t
                    w.refresh()

    def drag_drop(self, x: int, y: int, ctrl: bool) -> None:
        self.drag_move(x, y)
        for l in (self.main, self.parent_list):
            l.drop_row = None
            l.refresh()
        tgt, drag = self._drop, self._drag
        self._drop, self._drag, self.msg = None, [], ""
        self._status()
        if tgt and drag:
            paths = [e.path for e in drag]
            fn = (lambda: fsops.copy_paths(paths, tgt.path)) if ctrl else (lambda: fsops.move_paths(paths, tgt.path))
            self.main.selected.clear()
            self.bg(f"{'copying' if ctrl else 'moving'} {len(paths)} item(s) to {tgt.name}", fn,
                    done=f"{'copied' if ctrl else 'moved'} {len(paths)} item(s) to {tgt.name}")

    # ---------- quitting ----------
    def act_quit_cd(self) -> None:
        self.final_cwd = str(self.loc.path)
        self.exit()

    def act_quit(self) -> None:
        self.final_cwd = None
        self.exit()
