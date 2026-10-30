import asyncio
from pathlib import Path
from vorgan.app import VorganApp
from vorgan.model import Loc
from vorgan.config import State


async def settle(pilot, app, n=3):
    for _ in range(n):
        await app.workers.wait_for_complete()
        await pilot.pause(0.15)


def mk(tree, tmp_path):
    return VorganApp(tree, scheme=tmp_path / "nope.json", state=State())


async def test_starts_and_lists(tree, tmp_path):
    app = mk(tree, tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot, app)
        names = [e.name for e in app.main.view]
        assert names[:5] == ["Documents", "Downloads", "Music", "Pictures", "Projects"]
        assert ".hidden" not in names and "notes.md" in names


async def test_keys_navigate_and_back(tree, tmp_path):
    app = mk(tree, tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot, app)
        await pilot.press("j")
        assert app.main.entry().name == "Downloads"
        await pilot.press("k", "l")          # enter Documents
        await settle(pilot, app)
        assert app.loc.path.name == "Documents"
        await pilot.press("h")
        await settle(pilot, app)
        assert app.loc.path == tree and app.main.entry().name == "Documents"


async def test_hidden_toggle_and_filter(tree, tmp_path):
    app = mk(tree, tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot, app)
        await pilot.press("full_stop")
        await settle(pilot, app)
        assert ".hidden" in [e.name for e in app.main.view]
        await pilot.press("slash")
        await pilot.press("n", "o", "t")
        await pilot.pause(0.2)
        assert [e.name for e in app.main.view] == ["notes.md"]
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert len(app.main.view) > 3


async def test_mouse_click_select_and_open(tree, tmp_path):
    app = mk(tree, tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot, app)
        await pilot.click("#main", offset=(5, 2))
        assert app.main.cursor == 2
        await pilot.click("#main", offset=(5, 0), control=True)
        await pilot.click("#main", offset=(5, 1), control=True)
        assert app.main.selected == {"Documents", "Downloads", "Music"} or len(app.main.selected) >= 2
        await pilot.click("#main", offset=(5, 4))
        await pilot.click("#main", offset=(5, 4))
        await settle(pilot, app)
        assert app.loc.path.name == "Projects"


async def test_hint_jump(tree, tmp_path):
    app = mk(tree, tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot, app)
        await pilot.press("f")
        assert app.hint == "" and app.main.hints
        tag = app.main.hints[4]
        for ch in tag:
            await pilot.press(ch)
        await settle(pilot, app)
        assert app.loc.path.name == "Projects"


async def test_column_resize_persists(tree, tmp_path):
    app = mk(tree, tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot, app)
        app.resize_pane("parent", 36)       # 36/120 -> 30%
        app.save_panes()
        assert app.state.cols == {"parent": 30}


async def test_image_and_text_preview(tree, tmp_path):
    app = mk(tree, tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot, app)
        await pilot.press("j", "j", "j", "l")   # into Pictures
        await settle(pilot, app)
        assert app.main.entry().name == "pic.png"
        await settle(pilot, app, 4)
        from rich.console import Console
        c = Console(width=60, record=True, file=open("/dev/null", "w"))
        c.print(app.preview.last)
        out = c.export_text()
        assert "▀" in out and "64×32" in out
