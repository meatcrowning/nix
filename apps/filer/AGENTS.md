# `filer` — Qt/QML file browser

Vendored source of the standalone file browser: its own self-contained flake,
plus `main.py` and `qml/`. Built and installed by `home/prog/filer.nix`, which
wraps `python3` around the **live** source at `/home/lam/nix/apps/filer/main.py`
— see [`../AGENTS.md`](../AGENTS.md) for the live-source rules that apply to all
five apps.

- A compat symlink `~/Projects/filer → ~/nix/apps/filer` preserves the old
  source path.
- filer's own flake builds on `x86_64-linux` + `aarch64-linux`, so
  `nix run ~/nix/apps/filer` and `run.sh` work on book too.
- `openFile` shells out to `viewer <path>` for images — the image overlay used
  to live in here and was split out into [`../viewer`](../viewer/AGENTS.md).
- Titlebar chrome comes from hyprvtb via `pylib/vtbclient.py`.
