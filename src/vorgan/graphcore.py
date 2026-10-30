"""Graph navigator core: folder bubbles, physics, hit testing and a Braille renderer.

Pure logic with no Textual code, so it can be tested without a screen.
World units are "normalised": near ring = 64, far ring = 150.
"""
from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

from rich.style import Style
from rich.text import Text

from . import archive
from .model import Loc, is_archive_name
from .theme import Palette, mix

NEAR, FAR = 64.0, 150.0
BIT = [0x01, 0x08, 0x02, 0x10, 0x04, 0x20, 0x40, 0x80]
MAX_GRAND = 5


@dataclass(eq=False)
class GNode:
    loc: Loc
    name: str
    role: str                 # c centre, p parent, k child, g grandchild, m "more" bubble
    par: "GNode | None" = None
    count: int = 0
    arc: bool = False
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    old: bool = False

    @property
    def key(self) -> str:
        return self.loc.display()

    @property
    def radius(self) -> float:
        if self.role == "c":
            return 36.0
        if self.role == "g":
            return 6.0
        if self.role == "p":
            return 16.0
        if self.role == "m":
            return 13.0
        if self.arc:
            return 18.0
        return 14.0 + min(self.count, 12) * 1.6


def count_loc(loc: Loc, cap: int = 1000) -> int:
    try:
        if loc.arc:
            return len(archive.get_index(loc.arc).children(loc.inner))
        with os.scandir(loc.path) as it:
            return sum(1 for _ in islice(it, cap))
    except (OSError, archive.ArchiveError):
        return 0


def list_kids(loc: Loc, show_hidden: bool) -> list[tuple[Loc, str, bool]]:
    """Folders (and archives) inside loc: (location, name, is_archive)."""
    out: list[tuple[Loc, str, bool]] = []
    try:
        if loc.arc:
            for e in archive.get_index(loc.arc).children(loc.inner):
                if e.is_dir and (show_hidden or not e.hidden):
                    out.append((Loc(loc.path, loc.arc, e.inner), e.name, False))
        else:
            with os.scandir(loc.path) as it:
                for de in it:
                    if not show_hidden and de.name.startswith("."):
                        continue
                    try:
                        if de.is_dir():
                            out.append((Loc(Path(de.path)), de.name, False))
                        elif is_archive_name(de.name):
                            out.append((Loc(loc.path, Path(de.path), ""), de.name, True))
                    except OSError:
                        continue
    except (OSError, archive.ArchiveError):
        return []
    out.sort(key=lambda t: (t[2], t[1].lower()))
    return out


class Canvas:
    """Braille dot canvas: every terminal cell is 2 dots wide and 4 dots tall."""

    def __init__(self, W: int, H: int):
        self.W, self.H = W, H
        self.bits = [0] * (W * H)
        self.col: list = [None] * (W * H)
        self.pr = [-1] * (W * H)
        self.over: dict[tuple[int, int], tuple[str, object]] = {}

    def plot(self, x: int, y: int, c, p: int = 0) -> None:
        if x < 0 or y < 0:
            return
        cx, cy = x >> 1, y >> 2
        if cx >= self.W or cy >= self.H:
            return
        i = cy * self.W + cx
        self.bits[i] |= BIT[((y & 3) << 1) | (x & 1)]
        if p >= self.pr[i]:
            self.pr[i] = p
            self.col[i] = c

    def line(self, x0: float, y0: float, x1: float, y1: float, c, p: int = 1, dash: int = 0) -> None:
        x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err, k = dx + dy, 0
        for _ in range(4000):
            if not dash or (k // dash) % 2 == 0:
                self.plot(x0, y0, c, p)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
            k += 1

    def circle(self, cx: float, cy: float, r: int, c, p: int = 3, dotted: bool = False) -> None:
        cx, cy = int(round(cx)), int(round(cy))
        x, y, err, k = r, 0, 1 - r, 0
        while x >= y:
            if not dotted or k % 2 == 0:
                for ax, ay in ((x, y), (y, x), (-y, x), (-x, y), (-x, -y), (-y, -x), (y, -x), (x, -y)):
                    self.plot(cx + ax, cy + ay, c, p)
            y += 1
            k += 1
            if err < 0:
                err += 2 * y + 1
            else:
                x -= 1
                err += 2 * (y - x) + 1

    def disc(self, cx: float, cy: float, r: int, c, p: int = 1, every: int = 3) -> None:
        cx, cy = int(round(cx)), int(round(cy))
        for yy in range(-r, r + 1):
            half = int(math.sqrt(max(0, r * r - yy * yy)))
            for xx in range(-half, half + 1):
                if (xx + yy) % every == 0:
                    self.plot(cx + xx, cy + yy, c, p)

    def put(self, col: int, row: int, s: str, style) -> None:
        for k, ch in enumerate(s):
            if 0 <= col + k < self.W and 0 <= row < self.H:
                self.over[(col + k, row)] = (ch, style)

    def to_text(self) -> Text:
        rows: list[Text] = []
        W = self.W
        for cy in range(self.H):
            t = Text(no_wrap=True, overflow="crop")
            run, rs = [], None
            for cx in range(W):
                i = cy * W + cx
                ov = self.over.get((cx, cy))
                if ov:
                    ch, sk = ov
                elif self.bits[i]:
                    ch, sk = chr(0x2800 + self.bits[i]), self.col[i]
                else:
                    ch, sk = " ", None
                if sk is not rs:
                    if run:
                        t.append("".join(run), rs)
                    run, rs = [], sk
                run.append(ch)
            if run:
                t.append("".join(run), rs)
            rows.append(t)
        return Text("\n").join(rows)


class Graph:
    def __init__(self, loc: Loc, state, palette: Palette, show_hidden: bool = False, maxn: int = 28):
        self.state, self.pal = state, palette
        self.show_hidden, self.maxn = show_hidden, maxn
        self.zoom, self.page = 1.0, 0
        self.pos: dict[str, tuple[float, float]] = {}
        self.W = self.H = 0
        self.nodes: list[GNode] = []
        self.loc = loc
        self.set_palette(palette)
        self.rebuild()

    # ---------- styles ----------
    def set_palette(self, p: Palette) -> None:
        self.pal = p
        S = lambda c, **k: Style(color=c, **k)
        self.sty = {
            "edge": S(mix(p.bg, p.faint, 0.8)), "hi": S(p.accent), "ring": S(mix(p.bg, p.faint, 0.45)),
            "c": S(p.accent), "k": S(p.kinds["dir"]), "arc": S(p.kinds["archive"]), "g": S(p.faint),
            "p": S(p.dim), "m": S(p.accent2), "pin": S(p.pin),
            "lc": S(p.text, bold=True), "lk": S(p.text), "larc": S(p.kinds["archive"]), "lg": S(p.dim),
            "lp": S(p.dim), "lpin": S(p.pin, bold=True), "lm": S(p.accent2),
            "lh": Style(color=p.bg, bgcolor=p.accent, bold=True), "dim": S(p.faint),
        }

    # ---------- building ----------
    def _mk(self, loc: Loc, name: str, role: str, par, count: int = 0, arc: bool = False) -> GNode:
        n = GNode(loc, name, role, par, count, arc)
        if n.key in self.pos:
            n.x, n.y = self.pos[n.key]
            n.old = True
        else:
            n.x, n.y = random.uniform(-30, 30), random.uniform(-30, 30)
        self.nodes.append(n)
        return n

    def rebuild(self) -> None:
        self.nodes = []
        loc = self.loc
        c = self._mk(loc, loc.crumbs()[-1][0], "c", None, count_loc(loc))
        c.x = c.y = 0.0
        par = loc.parent()
        if par:
            p = self._mk(par, par.crumbs()[-1][0], "p", c)
            if not p.old:
                p.x, p.y = -150.0, -110.0
        kids = list_kids(loc, self.show_hidden)
        pins = self.state.pins
        pinned = [k for k in kids if k[0].display() in pins]
        rest = [k for k in kids if k[0].display() not in pins]
        slots = max(4, self.maxn - len(pinned))
        pages = max(1, math.ceil(len(rest) / slots))
        self.page %= pages
        shown = pinned + rest[self.page * slots:(self.page + 1) * slots]
        for i, (kl, name, is_arc) in enumerate(shown):
            k = self._mk(kl, name, "k", c, 0 if is_arc else count_loc(kl), is_arc)
            if not k.old:
                t = i / max(1, len(shown)) * math.tau
                k.x, k.y = math.cos(t) * 120, math.sin(t) * 120
            if not is_arc:
                for gl, gname, _ in list_kids(kl, self.show_hidden)[:MAX_GRAND]:
                    g = self._mk(gl, gname, "g", k)
                    if not g.old:
                        g.x, g.y = k.x + random.uniform(-20, 20), k.y + random.uniform(-20, 20)
        if len(rest) > slots:
            m = self._mk(Loc(loc.path, loc.arc, loc.inner + "\0more"), f"+{len(rest) - slots} more", "m", c)
            if not m.old:
                m.x, m.y = 0.0, 140.0
        self.focus = -1

    @property
    def center(self) -> GNode:
        return self.nodes[0]

    def dive(self, node: GNode) -> None:
        if node.role == "c":
            return
        if node.role == "m":
            self.pos = {m.key: (m.x, m.y) for m in self.nodes if m.role in ("c", "p", "k")}
            self.page += 1
            self.rebuild()
            return
        self.pos = {m.key: (m.x - node.x, m.y - node.y) for m in self.nodes}
        self.loc, self.page = node.loc, 0
        self.rebuild()

    def up(self) -> bool:
        p = next((n for n in self.nodes if n.role == "p"), None)
        if p:
            self.dive(p)
            return True
        return False

    def reset_layout(self) -> None:
        self.pos = {}
        self.rebuild()

    def toggle_hidden(self) -> None:
        self.show_hidden = not self.show_hidden
        self.pos = {m.key: (m.x, m.y) for m in self.nodes}
        self.rebuild()

    # ---------- geometry ----------
    def set_size(self, W: int, H: int) -> None:
        self.W, self.H = W, H
        Wd, Hd = W * 2, H * 4
        self.xs = min(2.0, max(1.0, Wd / max(1, Hd) * 0.65))
        half = max(10.0, min(Hd / 2, Wd / (2 * self.xs)))
        self.sc = max(0.05, (half - 10) / 215.0)

    def to_dots(self, x: float, y: float) -> tuple[float, float]:
        return (self.W + x * self.sc * self.xs * self.zoom, self.H * 2 + y * self.sc * self.zoom)

    def to_world(self, dx: float, dy: float) -> tuple[float, float]:
        return ((dx - self.W) / (self.sc * self.xs * self.zoom), (dy - self.H * 2) / (self.sc * self.zoom))

    def rdots(self, n: GNode) -> int:
        return max(2 if n.role == "g" else 3, int(n.radius * self.sc * self.zoom))

    def node_at(self, dx: float, dy: float) -> GNode | None:
        for n in reversed(self.nodes):
            sx, sy = self.to_dots(n.x, n.y)
            if math.hypot(sx - dx, sy - dy) <= max(self.rdots(n), 4) + 3:
                return n
        return None

    # ---------- physics ----------
    def target(self, a: GNode) -> float:
        pin = self.state.pins.get(a.key)
        return pin if pin else FAR + min(a.count, 10) * 5

    def step(self, drag: GNode | None = None) -> float:
        N = self.nodes
        xl = (self.W - 8) / (self.sc * self.xs * self.zoom)
        yl = (self.H * 2 - 8) / (self.sc * self.zoom)
        energy = 0.0
        for a in N:
            if a.role == "c" or a is drag:
                continue
            fx = fy = 0.0
            for b in N:
                if a is b:
                    continue
                dx, dy = a.x - b.x, a.y - b.y
                d2 = dx * dx + dy * dy + 0.01
                d = math.sqrt(d2)
                R = 40 if a.role == "g" else 90
                if d < R * 1.6:
                    f = (260 if (a.role == "g" or b.role == "g") else 1400) / d2 * (1 - d / (R * 1.6))
                    fx += dx / d * f
                    fy += dy / d * f
            if a.role in ("k", "m"):
                d = math.hypot(a.x, a.y) or 1.0
                t = self.target(a) if a.role == "k" else FAR
                fx -= a.x / d * (d - t) * 0.06
                fy -= a.y / d * (d - t) * 0.06
            elif a.role == "p":
                fx += (-150 - a.x) * 0.03
                fy += (-110 - a.y) * 0.03
            else:
                dx, dy = a.x - a.par.x, a.y - a.par.y
                d = math.hypot(dx, dy) or 1.0
                fx -= dx / d * (d - 46) * 0.08
                fy -= dy / d * (d - 46) * 0.08
            if abs(a.x) > xl:
                fx -= math.copysign(abs(a.x) - xl, a.x) * 0.2
            if abs(a.y) > yl:
                fy -= math.copysign(abs(a.y) - yl, a.y) * 0.2
            a.vx = (a.vx + fx) * 0.8
            a.vy = (a.vy + fy) * 0.8
            if abs(a.vx) < 0.03 and abs(a.vy) < 0.03:
                a.vx = a.vy = 0.0
                continue
            a.x += a.vx
            a.y += a.vy
            energy += abs(a.vx) + abs(a.vy)
        return energy

    # ---------- pinning ----------
    def pin(self, n: GNode) -> None:
        if n.role == "k":
            self.state.set_pin(n.key, max(NEAR, math.hypot(n.x, n.y)))

    def unpin(self, n: GNode) -> bool:
        if n.key in self.state.pins:
            self.state.drop_pin(n.key)
            return True
        return False

    # ---------- rendering ----------
    def label(self, n: GNode) -> tuple[str, str]:
        pinned = n.key in self.state.pins
        name = n.name if len(n.name) <= 20 else n.name[:19] + "…"
        if n.role == "p":
            return "▲ " + name, "lp"
        if n.role == "c":
            return name, "lc"
        if n.role == "m":
            return name, "lm"
        if pinned:
            return "◆ " + name, "lpin"
        if n.arc:
            return name, "larc"
        return name, "lg" if n.role == "g" else "lk"

    def render(self, hover: GNode | None = None) -> Text:
        W, H = self.W, self.H
        if W < 8 or H < 4:
            return Text("")
        cv = Canvas(W, H)
        sty = self.sty
        near: set[int] = set()
        if hover:
            near.add(id(hover))
            for n in self.nodes:
                if n.par is hover or hover.par is n:
                    near.add(id(n))
        # faint dot lattice, the graph's ground
        ground = Style(color=mix(self.pal.bg, self.pal.faint, 0.16))
        for y in range(2, H * 4, 8):
            for x in range(3, W * 2, 8):
                cv.plot(x, y, ground, 0)
        # guide rings
        for R, lab in ((NEAR, "near"), (FAR, "far")):
            for deg in range(0, 360, 4):
                t = math.radians(deg)
                x, y = self.to_dots(math.cos(t) * R, math.sin(t) * R)
                if (deg // 4) % 2 == 0:
                    cv.plot(int(x), int(y), sty["ring"], 0)
            x, y = self.to_dots(math.cos(math.radians(-62)) * R, math.sin(math.radians(-62)) * R)
            cv.put(int(x) >> 1, int(y) >> 2, lab, sty["dim"])
        # edges, trimmed to the bubble rims
        for n in self.nodes:
            if n.par is None:
                continue
            on = hover is not None and (n is hover or n.par is hover)
            x0, y0 = self.to_dots(n.par.x, n.par.y)
            x1, y1 = self.to_dots(n.x, n.y)
            dx, dy = x1 - x0, y1 - y0
            L = math.hypot(dx, dy)
            if L > 1:
                ux, uy = dx / L, dy / L
                x0, y0 = x0 + ux * self.rdots(n.par), y0 + uy * self.rdots(n.par)
                x1, y1 = x1 - ux * self.rdots(n), y1 - uy * self.rdots(n)
            cv.line(x0, y0, x1, y1, sty["hi"] if on else sty["edge"], 6 if on else 1, dash=3 if n.role == "p" else 0)
        # bubbles: tinted fill under a clean outline; hover lights the fill up
        bcol = {"c": self.pal.accent, "k": self.pal.kinds["dir"], "arc": self.pal.kinds["archive"],
                "m": self.pal.accent2, "p": self.pal.dim}
        tint = {"c": 0.20, "k": 0.20, "arc": 0.20, "m": 0.18, "p": 0.14}
        order = {"g": 0, "p": 1, "m": 2, "k": 3, "c": 4}
        for n in sorted(self.nodes, key=lambda m: order[m.role]):
            sx, sy = self.to_dots(n.x, n.y)
            r = self.rdots(n)
            dim = hover is not None and id(n) not in near
            key = "c" if n.role == "c" else "arc" if n.arc else n.role if n.role in ("p", "m", "g") else "k"
            col = sty["g"] if dim and n.role != "c" else sty[key]
            if n.role == "g":
                cv.disc(sx, sy, max(1, r - 1), col, 4, every=1)
                continue
            t = tint[key]
            raw = bcol[key]
            if dim:
                raw, t = self.pal.faint, 0.10
            elif n is hover:
                raw, t = self.pal.accent, 0.42
            cv.disc(sx, sy, max(1, r - 1), Style(color=mix(self.pal.bg, raw, t)), 2, every=2)
            if n.role == "c":
                cv.disc(sx, sy, max(2, r // 2), col, 3, every=1)
                cv.circle(sx, sy, r + 2, col, 3, dotted=True)
            cv.circle(sx, sy, r, col, 5)
            if n.key in self.state.pins and n.role == "k":
                cv.circle(sx, sy, r + 3, sty["pin"], 7, dotted=True)
            if n is hover:
                cv.circle(sx, sy, r + 2, sty["hi"], 8)
        # labels (centre and hovered first so they always win)
        placed: list[tuple[int, int, int]] = []

        def put(n: GNode, force: bool = False) -> None:
            text, sk = self.label(n)
            style = sty["lh"] if n is hover else sty[sk]
            sx, sy = self.to_dots(n.x, n.y)
            c0 = int(sx) // 2 - len(text) // 2
            row0 = int(sy + self.rdots(n) + 3) // 4 + (1 if n.role != "c" else 1)
            for dr in (0, 1, 2):
                row = row0 + dr
                if not (0 <= row < H):
                    break
                if all(not (r == row and not (c0 + len(text) < a or c0 > b)) for r, a, b in placed):
                    cv.put(max(0, c0), row, text, style)
                    placed.append((row, c0 - 1, c0 + len(text) + 1))
                    return
            if force and 0 <= row0 < H:
                cv.put(max(0, c0), row0, text, style)

        c = self.center
        put(c, True)
        if hover:
            put(hover, True)
        for n in self.nodes:
            if n.role in ("k", "m", "p") and n is not hover:
                put(n)
        for n in self.nodes:
            if n.role == "g" and id(n) in near and n is not hover:
                put(n)
        sx, sy = self.to_dots(c.x, c.y)
        num = str(c.count)
        cv.put(int(sx) // 2 - len(num) // 2, int(sy) // 4, num, sty["lc"])
        return cv.to_text()
