# `apps/` — the vendored desktop apps

Five standalone Qt/QML apps that ship with this config, plus the shared Python
helpers they all import. Each has its own `AGENTS.md` with the detail:

| dir | what it is | packaged by |
| --- | --- | --- |
| [`filer/`](filer/AGENTS.md) | Qt/QML file browser | `home/prog/filer.nix` |
| [`viewer/`](viewer/AGENTS.md) | image viewer (‹/› through a folder) | `home/prog/viewer.nix` |
| [`player/`](player/AGENTS.md) | tag-driven music player (mpv + MPRIS) | `home/prog/player.nix` |
| [`painter/`](painter/AGENTS.md) | text-to-image front end for headless ComfyUI | `home/prog/painter.nix` |
| [`surfer/`](surfer/AGENTS.md) | QtWebEngine browser | `home/prog/surfer.nix` |
| `pylib/` | shared helpers — see below | (imported, not packaged) |

## Why this tree is OUTSIDE `home/` and `sys/`

Non-negotiable: `home/default.nix` and `sys/default.nix` use `umport`, which
recursively imports **every** `.nix` file beneath them. An app parked in there
would have its own `flake.nix` eval'd as a NixOS module. `apps/` is inert
vendored source — nothing in the NixOS/home evaluation imports it, it simply
travels with the repo so a `git pull` carries the apps to every machine.

(This is why they sat at the repo *root* historically; the constraint was only
ever "outside `home/`/`sys/`", so `apps/` satisfies it just as well.)

## The live-source pattern — all five work this way

`home/prog/<app>.nix` builds a wrapper that runs the **live** source at the
absolute path `/home/lam/nix/apps/<app>/main.py` — valid on both `top` and
`air`, which is why it is absolute and not `${./.}`.

- **`.py`/`.qml` edits need NO rebuild.**
- **There is also NO hot-reload — relaunch the app** to pick a change up.
  (Only the Quickshell panel hot-reloads; these do not.)
- A rebuild is needed only when a change adds a **dependency** or edits the
  `.nix` packaging.
- Consequence for agents: after editing app source, do not rebuild reflexively,
  and do not relaunch the user's running app for them — say what to relaunch.

Each app also carries an **`air` split** in its `.nix`: on book (Fedora Asahi)
the wrapper `exec`s the system `/usr/bin/python3` rather than a nix-built
interpreter.

## `pylib/` — shared, resolved relatively

Every app does `sys.path.insert(0, str(HERE.parent / "pylib"))`, so the whole
`apps/` tree must move together or none of it does. Tools one level deeper use
`parent.parent.parent`.

- **`vtbclient.py`** — the hyprvtb titlebar-button socket bridge. Every app's
  chrome (transport buttons, close/zoom, view switchers) is drawn by the
  compositor plugin, not by QML, and goes through here.
- **`trackmatch.py`** — the one artist/title normaliser. Any new "are these two
  tag strings the same song?" code must use it rather than grow a second copy;
  see `player/AGENTS.md`.
- **`kitty-vtb.py`** — kitty's vtb integration, run from the live repo, stdlib
  only.

**Guard every rect you hand hyprvtb.** Hyprland's `renderRect` aborts the
compositor on a zero-size box, so an app feeding the vtb socket can take the
whole session down (the player's paused-at-0:00 `PLAYBAR` did exactly that).
Fixed plugin-side in v2.45, but guard on the app side too.

## Verifying changes

- **The user does ALL visual/animation/interaction checks.** Never screenshot or
  drive these GUIs yourself unless explicitly asked.
- **Never open a test window on the user's screen** — use `tools/sandbox.sh`
  (off-screen virtual monitor: `start` / `exec CMD` / `shot` / `clients` /
  `stop`).
- Syntax-check QML headlessly: `qmllint -I <qml import paths> qml/Main.qml`
  (import paths from the app's wrapper env). The "Failed to import" lines are
  missing paths, not errors.
- For app logic, write a headless PySide harness (e.g. pre-grant a permission
  and assert a signal fires) rather than clicking.
- QtWebEngine/permission/notification API details are best confirmed against the
  QML type defs (`plugins.qmltypes`) rather than guessed.
