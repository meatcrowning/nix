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
- **The wheel ZOOMS, and it is the one sanctioned bare `Flickable` in `apps/`.**
  `ImageViewer.qml`'s `WheelHandler` is delta-proportional — `exp(ln1.2/120·d)`,
  so one classic detent is still exactly x1.2 while a trackpad burst no longer
  slams the 1..8 range shut in a dozen events — and it consumes EVERY wheel
  event (all modifiers), so the Flickable underneath never gets one to flick
  with. That is why viewer is off `kinetic_deny_classes`: a compositor coast
  just keeps zooming smoothly and the clamp holds. Its `interactive: true` buys
  drag-panning only. Everything ELSE in `apps/` must use `../qmlcommon/`'s
  `Kinetic*` views — see [`../AGENTS.md`](../AGENTS.md).
