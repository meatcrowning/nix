# `filer` — Qt/QML file browser

Vendored source of the standalone file browser: its own self-contained flake,
plus `main.py` and `qml/`. Built and installed by `home/prog/filer.nix`, which
wraps `python3` around the **live** source at `/home/lam/nix/apps/filer/main.py`
— see [`../AGENTS.md`](../AGENTS.md) for the live-source rules that apply to all
five apps.

- A compat symlink `~/Projects/filer → ~/nix/apps/filer` preserves the old
  source path.
- filer's own flake declares both `x86_64-linux` and `aarch64-linux`, so `run.sh`
  (which is `nix develop` + the **live** `main.py`, the way filer is actually
  run) works on book too. **`nix run ~/nix/apps/filer` does NOT work** and has
  not since the app grew past one file: the `installPhase` copies only `main.py`
  and `qml/`, while `main.py` imports `videoconv`, `pick` (both beside it) and
  `vtbclient` (from `../pylib`, via `sys.path.insert(HERE.parent / "pylib")`) at
  module scope — so the packaged binary dies on the first import. The flake is
  kept for its `devShells`, which is what `run.sh` consumes; fixing `nix run`
  means copying those files and `../pylib` in, and `../pylib` is outside the
  flake's `src`.
- `openFile` shells out to `viewer <path>` for images — the image overlay used
  to live in here and was split out into [`../viewer`](../viewer/AGENTS.md).
- Titlebar chrome comes from hyprvtb via `pylib/vtbclient.py`.
- **The preview grid and the tree list are `KineticGridView` / `KineticListView`** (`../qmlcommon/`), not bare views — the desktop's momentum is compositor-side and Qt's own flick fights it. Any new scrollable surface here must use those too; see [`../AGENTS.md`](../AGENTS.md).

## Split view — two panes, one titlebar

`qml/BrowserPane.qml` **is** the file browser — tree, preview grid, selection,
context menu, drop target, dialogs. It used to be an inline
`Rectangle { id: view }` filling the window; it is a component so `Main.qml` can
put two of them side by side. The id stayed `view`, so every reference inside it
reads as it always did. `Main.qml` is now only the window and its chrome.

- **`sp` (or F3) toggles it; F6 moves the chrome to the other pane.** The right
  pane is a `Loader`, so an unsplit window pays for no second listing, watch set
  or thumbnail queue.
- **`win.pane` is the FOCUSED pane, and the chrome reads nothing else** — the
  title/address bar, the sort buttons, every file operation, the dir-size
  footer. Clicking anywhere in a pane points the chrome at it
  (`claimFocus()` → `focusClaimed` → `win.focusPane`); an accent frame says
  which. That is the same shape as surfer's split view
  (`../surfer/qml/Main.qml`) minus its hard part: surfer's panes hold *tabs*, so
  one pane being handed the other's view had to swap them. Two filer panes can
  show the same directory, and nothing has to be arbitrated.
- **Dragging between the panes is the point of it** — and needs no code of its
  own: they are two `DropArea`s in one process, so a drag from one to the other
  is the ordinary cross-window drop above, `move / copy / link` menu included.
- **Anything that acts on "the view" acts on EVERY pane** (`win.refreshAll`): a
  finished file op or an external change may well be visible in both, and a move
  between the panes *is* that case. `reselect` lands in whichever pane holds it.
- **`DirWatch.setDirs` is KEYED, one key per pane** (`main.py`). It used to
  replace the whole watch set, which with two panes meant the second pane's
  rebuild silently unwatched the first pane's directories. The watcher holds the
  union; a pane hands its key back on destruction.
- **Only the left pane persists dir/sort/hidden** — one `state.json` cannot hold
  two panes' sort orders. The right pane persists just `splitDir`, which with
  `split` and `splitRatio` is enough to restore the split as it was. A restored
  split points the chrome at the LEFT pane; opening one by hand focuses the new
  (right) one, because that is the pane you just asked for.
- **A picker is never split** (`filer --pick` is one transient errand): the `sp`
  button is disabled and `toggleSplit()` refuses.
- **The row's timestamp columns drop out, widest-first, below ~620/~470px** —
  three fixed columns in a half-width pane left the filename elided to nothing.
  They go to `width: 0`, not `visible: false`: the next column anchors to this
  one's left edge and an invisible item keeps its geometry.

Verify with `tools/split-test.py` (offscreen, 40 checks — geometry, which pane
the chrome follows, the watch union, a real drop into the right-hand pane, and
the restore). It redirects `Settings` into a temp dir, which any harness that
navigates or sorts **must** do or it rewrites where the user's own filer reopens.

## Drag and drop — both halves

**Drag out** is on the file rows (`qml/BrowserPane.qml`) and the preview tiles
(`qml/PreviewTile.qml`); **drop in** is one `DropArea` over the whole pane.
Two filer windows are two separate processes, so window-to-window dragging is
ordinary cross-app Wayland DnD — nothing about it is special-cased, and the same
gestures work against Dolphin, a browser upload field, the other half of a split
view, etc.

- **The payload is built on PRESS, not bound.** It depends on the selection, and
  a binding would re-run `FileOps.uriList` for every realised row/tile on every
  selection change.
- **A drag carries the whole selection** when it starts on an item that is part
  of a multi-selection. That needs the press *not* to collapse the selection, so
  a plain press inside an existing multi-selection defers its click to the
  release and applies it only if no drag happened (`deferSelect`/`dragged` in
  both `MouseArea`s). `dragged` latches on the way in because `drag.active` is
  already false again by the time `onReleased` runs.
- **`FileOps.uriList` / `urlsToPaths` (main.py) own the encoding.** `encodeURI`
  does *not* escape `#` or `?`, so a filename containing either used to drag out
  as a truncated path; `QUrl` does it properly. Don't hand-roll a `file://` URI
  here again.
- **A drop asks what it meant** — a `move / copy / link here` menu, the way
  Dolphin does. It is not a stylistic choice: the modifier keys never reach the
  destination process (Wayland keeps keyboard focus on the drag *source*, which
  is a different process, and the compositor does not vary the proposed action
  by modifier), so there is no signal to tell a move from a copy. Guessing would
  mean silently moving files on a hunch.
- **Three sources are dropped silently** by `dropCandidates`: one already in the
  target dir, a directory dropped onto itself, and a directory dropped into its
  own subtree. The last one is a `cp -a` that eats the disk.
- Transfers reuse the paste machinery — `transferInto` → `runPaste` — so a drop
  gets the same no-clobber default and overwrite confirm a paste does.

Verify with `tools/drop-test.py` (offscreen; posts real `QDragEnter`/`QDrop`
events at the window, so the DropArea, the target hit-test and the transfer are
all exercised without a window on anyone's screen).

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
picker branch in `qml/BrowserPane.qml` is gated on the pane's `picking`
(`Picker.active`, threaded in by `Main.qml`), so an ordinary filer window is
unchanged; notably `openFile()` returns the
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
    estimate. `BrowserPane.qml` calls it before doing anything: `plan.ask` (a slow
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
