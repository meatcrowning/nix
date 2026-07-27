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
- **The preview grid and the tree list are `KineticGridView` / `KineticListView`** (`../qmlcommon/`), not bare views — the desktop's momentum is compositor-side and Qt's own flick fights it. Any new scrollable surface here must use those too; see [`../AGENTS.md`](../AGENTS.md).

## filer as the desktop's FILE PICKER (`portal.py` + `pick.py`) — ships DORMANT

`filer` can be the dialog that appears when an app says "Upload File". That is
**not** a MIME association (which is what makes it the default *directory*
handler — `home/prog/filer.nix` + `mime-defaults.nix`); it is the
`org.freedesktop.impl.portal.FileChooser` D-Bus **backend** interface, and it is
packaged separately by `home/prog/filer-portal.nix`.

```bash
filer-portal-switch status     # is it on, and what would xdp pick?
filer-portal-switch on         # writes ~/.config/xdg-desktop-portal/hyprland-portals.conf
filer-portal-switch off        # deletes it. No rebuild either way.
```

**It is installed but inert until you run `on`.** xdg-desktop-portal only
consults backends *named in a portals.conf*, so the `filer.portal` file on disk
changes nothing by itself — verified against xdp 1.22.1's own
`Using <x>.portal for <interface>` trace, not assumed.

Four things to know before touching any of it:

- **Backend selection is per INTERFACE, not per method.** Claiming FileChooser
  claims `OpenFile`, `SaveFile` *and* `SaveFiles`; there is no per-method
  fallback, and an `UnknownMethod` reaches the calling app as a broken dialog.
  So "implement OpenFile only" is not a thing that can be configured. What
  `portal.py` does instead is implement all three and **proxy** SaveFile and
  SaveFiles to the backend that answers them today (`gtk` on book, `kde` on
  top — `FILER_PORTAL_DELEGATE`), handle unchanged, so save dialogs are
  bit-for-bit what they were.
- **The backend's `Request` object has only `Close()` — there is no `Response`
  signal on this side.** A backend answers by *returning from the method*, which
  is why the reply is delayed. The `Response` signal apps see is emitted by xdp
  on the frontend object. Getting this backwards hangs every file dialog on the
  machine.
- **A hang is the worst outcome, worse than a wrong answer.** Every exit path
  ends in exactly one reply (`_Reply` latches it), an absent result file is read
  as "cancelled", and a picker that cannot even be spawned falls through to the
  delegate. `FILER_PORTAL_OPEN=delegate` turns the whole service into a
  pass-through, which is the way to bisect a problem without editing config.
- **On `book`, `filer-portal-switch on` currently changes nothing, and that is
  not the switch's fault.** `xdg-desktop-portal.service` carries
  `Requisite=graphical-session.target`, and that target has *never* been active
  on book (`ActiveEnterTimestamp` is empty; Hyprland starts outside a systemd
  graphical session — `hyprland.lua`'s exec-once block already works around the
  same gap by hand-starting easyeffects and udiskie). So the frontend
  `org.freedesktop.portal.Desktop` cannot D-Bus-activate at all:

  ```
  gdbus call --session --dest org.freedesktop.portal.Desktop \
    --object-path /org/freedesktop/portal/desktop \
    --method org.freedesktop.DBus.Properties.Get \
    org.freedesktop.portal.FileChooser version
  → Could not activate remote peer: startup job failed
  ```

  Every portal file dialog on book is already dead this way, long before any of
  this landed — GTK and Qt apps just fall back to their own dialogs and nobody
  noticed. `xdg-desktop-portal-gtk.service` runs only because it has plain
  `After=`, not `Requisite=`. Unblocking it is a session-startup change, which
  is ask-first territory; the narrow version is a user drop-in clearing the
  `Requisite=` for that one unit. `top` is unaffected — it reaches
  `graphical-session.target` normally via SDDM.
- **The picker is a SUBPROCESS** (`filer --pick <spec.json>`), not QML hosted in
  the backend, so a crash or a wedge costs one dialog instead of every future
  one — and `Close()` has something to kill. The two halves talk only through
  the spec/result JSON described in `pick.py`, which is what lets each be tested
  without the other.

Picker mode reuses the whole browser — tree, expand, sort, preview grid,
titlebar address bar — and adds `qml/PickerBar.qml` along the bottom. Every
picker branch in `qml/Main.qml` is gated on `win.picking` (`Picker.active`), so
an ordinary filer window is unchanged; notably `openFile()` returns the
selection instead of shelling out to `viewer`/`xdg-open` (which would be
circular), and `persist()` no-ops so a dialog never moves where your real filer
window reopens.

**Verify headlessly, never by opening a dialog** — a malformed response hangs
the app that asked, so the "obvious" test is the one test you must not run:

```bash
apps/filer/tools/portal-tests.sh    # ~40 checks, no window, no session bus touched
```

Three harnesses: the D-Bus contract against a stub delegate and a stub `filer`
on a private bus (`dbus-run-session`); the picker by loading the real `Main.qml`
under `QT_QPA_PLATFORM=offscreen`; and the seam between them, the real backend
spawning the real `filer --pick`. Most of it is failure paths — cancel, crash,
missing binary, `Close()` mid-flight — because each of those is a candidate
hang.

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
