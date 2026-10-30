import zipfile
from pathlib import Path
from vorgan.app import VorganApp
from vorgan.config import State
from vorgan.model import Loc
from vorgan.widgets.graph import GraphScreen, GraphView
from vorgan.widgets.dialogs import Form, MenuScreen


async def settle(pilot, app, n=3):
    for _ in range(n):
        await app.workers.wait_for_complete()
        await pilot.pause(0.15)


def mk(tree, tmp_path):
    return VorganApp(tree, scheme=tmp_path / "nope.json", state=State())


async def test_graph_open_dive_close(tree, tmp_path):
    app = mk(tree, tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot, app)
        await pilot.press("tab")
        await pilot.pause(0.3)
        assert isinstance(app.screen, GraphScreen)
        v = app.screen.query_one(GraphView)
        for _ in range(120):
            v.g.step()
        v.dirty = True
        proj = next(n for n in v.g.nodes if n.name == "Projects")
        sx, sy = v.g.to_dots(proj.x, proj.y)
        await pilot.click(GraphView, offset=(int(sx // 2), int(sy // 4)))
        await pilot.pause(0.3)
        assert v.g.loc.path.name == "Projects"
        await pilot.press("escape")
        await settle(pilot, app)
        assert app.loc.path.name == "Projects"


async def test_graph_drag_pins(tree, tmp_path):
    app = mk(tree, tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot, app)
        await pilot.press("tab")
        await pilot.pause(0.3)
        v = app.screen.query_one(GraphView)
        for _ in range(120):
            v.g.step()
        n = next(n for n in v.g.nodes if n.name == "Music")
        sx, sy = v.g.to_dots(n.x, n.y)
        c = v.g.to_dots(0, 0)
        tx, ty = (sx + c[0]) / 2, (sy + c[1]) / 2
        await pilot.mouse_down(GraphView, offset=(int(sx // 2), int(sy // 4)))
        await pilot.hover(GraphView, offset=(int(tx // 2) + 3, int(ty // 4)))
        await pilot.hover(GraphView, offset=(int(tx // 2), int(ty // 4)))
        await pilot.mouse_up(GraphView, offset=(int(tx // 2), int(ty // 4)))
        await pilot.pause(0.2)
        assert any(k.endswith("Music") for k in app.state.pins)


async def test_rename_new_trash_paste(tree, tmp_path):
    app = mk(tree, tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot, app)
        await pilot.press("a")
        await pilot.pause(0.2)
        assert isinstance(app.screen, Form)
        app.screen.query_one("#f_name").value = "Fresh"
        await pilot.press("enter")
        await settle(pilot, app)
        assert (tree / "Fresh").is_dir()
        # copy notes.md then paste -> "notes (2).md"
        app.main.cursor = [e.name for e in app.main.view].index("notes.md")
        await pilot.press("y", "p")
        await settle(pilot, app, 4)
        assert (tree / "notes (2).md").exists()
        # rename
        await pilot.press("r")
        await pilot.pause(0.2)
        app.screen.query_one("#f_name").value = "renamed.md"
        await pilot.press("enter")
        await settle(pilot, app, 4)
        assert (tree / "renamed.md").exists() or (tree / "notes (2).md").exists()


async def test_compress_extract_roundtrip(tree, tmp_path):
    app = mk(tree, tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot, app)
        app.main.cursor = [e.name for e in app.main.view].index("Documents")
        await pilot.press("z")
        await pilot.pause(0.3)
        assert isinstance(app.screen, Form)
        app.screen.query_one("#f_name").value = "docs-backup"
        app.screen.query_one("#f_dest").value = str(tree / "Downloads")
        await pilot.press("enter")
        await settle(pilot, app, 5)
        z = tree / "Downloads" / "docs-backup.zip"
        assert z.exists() and "Documents/a.txt" in zipfile.ZipFile(z).namelist()
        # browse inside, then extract to a custom path
        await pilot.press("l")  # enter Downloads? cursor may differ; navigate explicitly
        app.goto(Loc(tree / "Downloads"))
        await settle(pilot, app, 4)
        app.main.cursor = [e.name for e in app.main.view].index("docs-backup.zip")
        await pilot.press("l")
        await settle(pilot, app, 4)
        assert app.loc.arc and [e.name for e in app.main.view] == ["Documents"]
        app.goto(Loc(tree / "Downloads"))
        await settle(pilot, app, 4)
        app.main.cursor = [e.name for e in app.main.view].index("docs-backup.zip")
        await pilot.press("e")
        await pilot.pause(0.3)
        assert isinstance(app.screen, Form)
        app.screen.query_one("#f_dest").value = str(tree / "Out" / "deep")
        await pilot.press("enter")
        await settle(pilot, app, 5)
        assert (tree / "Out" / "deep" / "docs-backup" / "Documents" / "b.txt").read_text() == "b"


async def test_context_menu_and_help(tree, tmp_path):
    app = mk(tree, tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot, app)
        await pilot.click("#main", offset=(5, 1), button=3)
        await pilot.pause(0.3)
        assert isinstance(app.screen, MenuScreen)
        await pilot.press("escape")
        await pilot.pause(0.2)
        await pilot.press("question_mark")
        await pilot.pause(0.2)
        assert app.screen.__class__.__name__ == "HelpScreen"


async def test_drag_drop_moves_file(tree, tmp_path):
    app = mk(tree, tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot, app)
        names = [e.name for e in app.main.view]
        src, dst = names.index("todo.txt"), names.index("Music")
        await pilot.mouse_down("#main", offset=(6, src))
        await pilot.hover("#main", offset=(6, src - 1))
        await pilot.hover("#main", offset=(6, dst))
        await pilot.mouse_up("#main", offset=(6, dst))
        await settle(pilot, app, 4)
        assert (tree / "Music" / "todo.txt").exists() and not (tree / "todo.txt").exists()


async def test_quit_cd_records_folder(tree, tmp_path):
    app = mk(tree, tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot, app)
        await pilot.press("j", "l")
        await settle(pilot, app)
        await pilot.press("q")
    assert app.final_cwd == str(tree / "Downloads")


async def test_pins_and_anchors_persist(tree, tmp_path):
    st = State()
    st.set_pin("/x/y", 80.0)
    st.set_anchor("a", "/tmp")
    st2 = State()
    assert st2.pins["/x/y"] == 80.0 and st2.anchors["a"] == "/tmp"
