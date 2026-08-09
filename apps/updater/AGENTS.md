# `updater` — the GUI for this flake's package updates

Vendored source of the standalone package-update GUI: `main.py` and `qml/`.
Built and installed by `home/prog/updater.nix`, which mirrors `reader.nix`
exactly (including the `air` system-python split) and runs the **live** source
at `/home/lam/nix/apps/updater/main.py`, so `.py`/`.qml` edits need no rebuild.
See [`../AGENTS.md`](../AGENTS.md) for the rules shared by all the apps, and
`~/nix/docs/DESIGN.md` before you draw anything.

It exists because he asked for "a gui for the package manager. so i can check
for updates, update only specific packages or everything at the same time."

## "Packages" here are flake INPUTS, and three of them are PINNED

There is no package manager to wrap — this machine is a flake, and what he
calls a package is a flake **input** in `flake.lock`. `nixpkgs` tracks
nixos-unstable and rolls; `hyprland`, `hyprland-air` and `nixpkgs-quickshell`
are frozen to exact revisions on purpose (`flake.nix` says why at length — a
routine bump used to cost the session its titlebars or its panel), and **a pin
bump is on his ask-first list** (root `AGENTS.md` → Boundaries).

`PINNED` in `main.py` is the one list of those three, and it drives two rules:

- **"update everything" never touches a pin.** `Inputs.nonPinnedNames()`
  filters them out, so `up` maps to `nix flake update <every non-pinned,
  updatable input>`, not a bare `nix flake update` (which would move all of
  them).
- **A single pin bump is allowed but guarded.** Its row still has an `update`
  button, drawn in `crit`, and it opens the confirm overlay in the pinned
  variant — a second, explicit confirmation that states it is ask-first and
  what it costs (a from-source hyprland build on book, no live plugin hot-swap
  until next login). Keep both halves if you touch it: an app that silently
  bumps a pin is exactly the affordance-honesty failure docs/DESIGN.md §10
  forbids.

## Three jobs, and the code splits along them

| button | what it runs | reinvents nothing |
|---|---|---|
| `ck` | `tools/nix-upgradable.sh --no-build` | the read-only preview: hardlink-copies the tree, `nix flake update`s the COPY, diffs — **the real `flake.lock` is never touched** |
| `c+` | `tools/nix-upgradable.sh` (full) | same, but builds the closures and diffs them (slow) |
| `up` | `nix flake update <non-pinned…>` then the rebuild wrapper | the actual apply |
| a row's `update` | `nix flake update <one>` then the rebuild wrapper | a single input, pins behind the second confirm |
| `x` | terminates the running job | — |

- **Checking is `tools/nix-upgradable.sh`, streamed verbatim** into the log
  pane. That script already computes the upgradable closures and diffs; this
  app calls it and reinvents none of it. (It cleans its own temp dir, so a
  per-row "update available" marker would need its own small lock-diff — left
  out for now precisely to avoid a second copy of what that tool does.)
- **Applying is `nix flake update` then this host's wrapper** — `sudo
  rebuild-top` on top, `rebuild-air` on book (`rebuild_cmd()` picks by
  `platform.machine()`). Both wrappers own preflight and the shared rebuild
  lock, so this app runs neither itself.
- **It never commits `flake.lock`.** The apply rewrites it; reviewing and
  committing it stays his, and the confirm overlay says so.

## Structure

- `Palette` / `DeskStyle` / `theme/Theme.qml` — the wal palette watched out of
  the panel's `Theme.qml` and the desktop font/size through `DeskStyle`,
  installed as context properties before `Theme.qml` is created, exactly like
  every other app.
- `Titlebar` (`pylib/vtbclient.py`) — updater's **whole chrome** is titlebar
  buttons drawn by the compositor plugin (`ck c+ | up | x`) plus a footer that
  shows the running job. Nothing in QML draws a titlebar strip (docs/DESIGN.md
  §12).
- `Inputs` — reads `flake.lock` directly (fast and always accurate for what is
  *locked*), watched with a `QFileSystemWatcher` so an external `nix flake
  update` or this app's own apply refreshes the list in place. `follows` inputs
  and non-revision inputs are shown but not offered an update.
- `Runner` — one `QProcess` at a time, a job being a label plus ordered steps
  (each an argv list) that stop on the first non-zero exit; `busy` gates every
  action in QML so two jobs cannot overlap and the pinned confirm cannot be
  raced.
- `Settings` / `Host` — the app's own persisted UI state
  (`~/.local/state/updater/state.json`, docs/DESIGN.md §14) and a couple of
  host facts the cost warning reads (`isBook`, the rebuild command string).

## Packaging notes (`home/prog/updater.nix`)

`reader.nix` pattern: `pyEnv = python3 + pyside6` on top, system `/usr/bin/python3`
on book, both running the live source. **No extra runtime deps** — it draws
text and shells out. The subprocesses (`nix`, `nix-upgradable.sh`, the rebuild
wrapper) are resolved from the session `PATH`, not pinned, because the wrapper
is host-specific by construction and the rest are his own live tools.

- **No `MimeType=`** — like painter and goetia, it has no honest file to open
  (it is a GUI over the flake), so it declares no association and is absent from
  `mime-defaults.nix` (`../AGENTS.md`).
- The icon is `home/prog/app-icons/updater.svg`, declared in `my.appSeals` so
  the panel paints its currentColor strokes in the focus colour.

## Gotchas (paid for once already)

- **QML imports must be `QtQuick.Controls.Basic`, never bare
  `QtQuick.Controls`.** The bare import pulls `org.kde.breeze` → kirigami, which
  is not on this machine, and the app dies with `Type ScrollBar unavailable`.
- **`VScroll.barW` is reached through an `id`, never as an attached type.**
  `ScrollBar.vertical: VScroll { id: listScroll }`, then `listScroll.barW` — a
  delegate that reserves the gutter must read the real bar width (§9.2), and it
  is a setting (11–16px), not a literal.
- **Board tools need goetia's pyEnv python**, not the system one (no PySide6):
  `/nix/store/…-python3-*-env/bin/python3 apps/board/tools/boardctl.py …`.

## Verifying

Same rules as every app in `../AGENTS.md` → "Verifying changes": **he does all
visual checks**, harnesses run `QT_QPA_PLATFORM=offscreen`, never a window on
his screen. A clean offscreen load (no stderr) proves the QML parses and the
context properties wire; the real actions shell out to `nix`/the rebuild
wrapper and must **not** be driven against his live flake from a test.
