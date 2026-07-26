# `viewer` — image viewer

Vendored source of the standalone image viewer (its own self-contained flake —
`main.py`, `qml/`). Built/installed by `home/prog/viewer.nix`, which mirrors
`filer.nix` exactly, including the `air` system-python split; it runs the
**live** source at `/home/lam/nix/apps/viewer/main.py`, so edits need no
rebuild. See [`../AGENTS.md`](../AGENTS.md) for the shared rules.

- **Split out of filer's old built-in overlay.** filer's `openFile` now shells
  out to `viewer <path>`, and viewer scans that file's directory for the sibling
  images, so ‹/› flip through the folder.
- Its prev/next/zoom/fit/close controls live in the **hyprvtb titlebar** (the
  same `pylib/vtbclient.py` bridge filer/surfer use), not in QML.
