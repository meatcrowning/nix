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
- **`videoconv.py`** — the context menu's "compress to <10MB" (an upload-limit
  squeeze). Exposed as the `VideoConv` context property; the only part of filer
  that shells out to `ffmpeg`/`ffprobe`/`notify-send` (all PATH-resolved from the
  user profile, like `gio`/`kitty` — nothing was added to `filer.nix`, so a
  missing tool surfaces as a failure toast, not a broken build).
  - `plan(path)` is pure and cheap (one ffprobe) and decides *everything* —
    resolution rung, fps, audio/video bitrate split, encoder, and an encode-time
    estimate. `Main.qml` calls it before doing anything: `plan.ask` (a slow
    encode, or a budget too tight to look good) puts a confirm in front of the
    user; otherwise the job just starts. Read its module docstring before
    changing the sizing — the ladder and the CRF-with-a-VBV-cap rate control are
    the two decisions everything else follows from.
  - `start(path)` runs ffmpeg through `QProcess` and reports **only** through
    desktop toasts (notify-send `--replace-id`, the same in-place-updating trick
    as surfer's downloads), so the window never blocks and nothing in the UI has
    to model progress. `finished(outPath)` just moves the selection.
  - Encoder policy: libx264 unless the estimate is slow *and* NVENC exists —
    x264 is much better at these bitrates and, on `top`, faster than the GPU for
    a short clip. book has no NVENC and falls through to x264 automatically.
  - The output is verified against the 10MB line after the encode; one
    corrective pass runs if it somehow overshot.
