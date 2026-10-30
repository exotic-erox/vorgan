# Architecture

```
 you (mouse / keyboard)
        |
 UI layer (Textual)            widgets/: filelist, graph, preview, dialogs, chrome
        |  commands / state
 App (app.py)                  navigation, selection, clipboard, background jobs
        |
 Core, no UI code              model.py  graphcore.py  fsops.py  archive.py
        |
 Files · Archives (bsdtar) · Preview · Theme · Config · fish
```

**One rule:** the core never imports the UI. That is why `graphcore.py` (bubbles, physics, Braille drawing)
and the file and archive code are tested without a screen.

**Archives behave like folders.** `Loc` is either a real folder or a folder inside an archive. `archive.ArcIndex`
turns `bsdtar -tvf` output into a tree, so double-clicking `backup.zip` walks into it.

## Modules

| Module | Job |
|---|---|
| `model.py` | `Entry`, `Loc`, file kinds, icons, sorting, fuzzy match |
| `fsops.py` | list, copy, move, trash (`gio trash`), rename, create |
| `archive.py` | list, extract (all or some members), compress (zip, tar.gz, tar.zst, tar.xz, 7z), read a member |
| `graphcore.py` | bubble graph: build, physics, hit-testing, Braille renderer |
| `theme.py` | read Caelestia `scheme.json` into a palette |
| `config.py` | TOML config, key map, pins and anchors |
| `shellx.py` | frequent folders from fish history |
| `app.py` | the Textual app |
| `widgets/` | file list, graph screen, preview, dialogs and menus, toolbar and trail |

## Graph internals

World units are fixed (near ring 64, far ring 150) and scaled to the terminal. Each terminal cell holds
2x4 Braille dots, so circles and lines are drawn as dots; labels are real text on top. Physics: nodes repel,
children are pulled to a ring (pinned ones to the radius you dropped them at), grandchildren follow their parent.
The simulation sleeps when settled, so an idle graph uses no CPU.

## Speed rules

- Folders and archives load in a background worker; the UI never blocks on disk.
- Previews run in cancellable background workers.
- Copy, move, extract and compress run in background workers with a status message.
- Only visible rows are drawn.
