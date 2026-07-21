# filer

A standalone Qt/QML file browser for the `top` desktop, ported out of the
Quickshell panel so it runs as its **own process**.

## Why it exists

The file browser started life as `FileBrowser.qml` inside the Quickshell panel
(`~/nix/home/prog/quickshell-files`). It was already a real window (a Quickshell
`FloatingWindow`, framed by the `hyprvtb` plugin), but it lived inside the
`quickshell` process — so **every Quickshell config hot-reload** (including the
one `wal-set.sh` triggers by rewriting `Theme.qml` on each wallpaper change)
tore it down and recreated it. This project lifts it into its own PySide6
process so reloads of the panel no longer touch it, and so it has room to grow
into a full-featured file manager without fighting the shell framework.

## What changed in the port

The QML is almost entirely unchanged. Only the Quickshell-specific bits were
swapped for a thin PySide6 host (`main.py`):

| Quickshell (panel)                 | filer (standalone)                                   |
| ---------------------------------- | ---------------------------------------------------- |
| `FloatingWindow`                   | `QtQuick.Window` (still framed by `hyprvtb`)          |
| `Quickshell.Io.Process`            | `FileOps.run(argv, reselect)` → `QProcess` (async)    |
| `Quickshell.execDetached`          | `FileOps.execDetached(argv)` → `QProcess.startDetached`|
| `Theme` singleton (auto-exposed)   | `Theme` context property (`qml/theme/Theme.qml`), colours bound to the live `WalPalette` |
| `Browsers` registry (multi-window) | dropped — single window for now                       |

`PixelText.qml`, `BrowserButton.qml`, `BrowserPrompt.qml`, `BrowserConfirm.qml`
are **verbatim copies** of the panel's versions.

## Features

- Navigate: up, double-click, editable location bar with **Tab-completion**.
- **Inline directory tree**: `+/−` toggles expand dirs in place, with vertical
  guide lines denoting the branch structure.
- File ops: new / rename / copy / cut / paste / trash / delete (async, argv-safe).
- **Live theming**: colours track the wallpaper palette in real time (see below).

## Run it

```sh
filer               # installed wrapper (fast; from ~/nix, the runner uses this)
./run.sh            # dev: nix develop + python3 main.py
nix run .           # packaged binary (bakes a source snapshot)
```

Requires the `More Perfect DOS VGA` font (already installed on `top` at
`~/.local/share/fonts/`). Launchable from the Quickshell runner and set as the
default directory handler — see `~/nix/home/prog/filer.nix`.

## Palette / wallpaper sync

Colours are **live**. `main.py`'s `Palette` object parses the panel's
`~/.config/quickshell/Theme.qml` (the file `wal-set.sh` rewrites between the
`>>> wal palette` / `<<< wal palette` markers) and watches it with a
`QFileSystemWatcher`; it's exposed to QML as `WalPalette` (not `Palette` — that's
a built-in Qt Quick type name) and `qml/theme/Theme.qml` binds its colours to it.
Change the wallpaper and filer recolours in lock-step with the bar.

## Roadmap

See [ROADMAP.md](ROADMAP.md). Next up (Phase 1): keyboard navigation,
right-click context menu, hidden-files toggle, sort options.
