# `filer` — Qt/QML file browser

Vendored source of the standalone file browser: its own self-contained flake,
plus `main.py` and `qml/`. Built and installed by `home/prog/filer.nix`, which
wraps `python3` around the **live** source at `/home/lam/nix/apps/filer/main.py`
— see [`../AGENTS.md`](../AGENTS.md) for the live-source rules that apply to all
six apps.

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
- `openFile` shells out to `viewer <path>` for images **and video** — the image
  overlay used to live in here and was split out into
  [`../viewer`](../viewer/AGENTS.md).
- Titlebar chrome comes from hyprvtb via `pylib/vtbclient.py`.
- **The preview grid and the tree list are `KineticGridView` / `KineticListView`** (`../qmlcommon/`), not bare views — the desktop's momentum is compositor-side and Qt's own flick fights it. Any new scrollable surface here must use those too; see [`../AGENTS.md`](../AGENTS.md).

## Split view — two panes, one titlebar

`qml/BrowserPane.qml` **is** the file browser — tree, preview grid, selection,
context menu, drop target, dialogs. It used to be an inline
`Rectangle { id: view }` filling the window; it is a component so `Main.qml` can
put two of them side by side. The id stayed `view`, so every reference inside it
reads as it always did. `Main.qml` is now only the window and its chrome.

- **Two titlebar buttons, kitty's own: `|` splits RIGHT and `_` splits DOWN.**
  Same labels and meaning as `pylib/kitty-vtb.py`'s `vsplit`/`hsplit`, so the
  gesture is one gesture across the desktop. `_` and not kitty's `-` because a
  bare `-` is the **spacer token** in the vtb button-array protocol.
  - Each stays a **toggle**: the button matching the current orientation closes
    the split; the *other* one **re-orients in place**, keeping both panes and
    their directories (only the rects change, the trailing pane's `Loader` is
    never torn down). Off, either button opens in its own orientation.
  - Lit (state 1) on the active orientation, and **both disabled (state 2)
    while `picking`** — a picker is never split.
  - **F3** toggles in the current/last orientation, **Shift+F3** is "split the
    other way" (open stacked, or re-orient); **F6** moves the chrome to the
    other pane, in either orientation.
- **One geometry, projected on either axis.** `splitVertical` picks the axis;
  `paneLeadSize`/`paneTrailPos`/`paneTrailSize` are measured along it and
  `paneLeadW/H`, `paneTrailX/Y/W/H` are the rects that fall out. One
  `splitRatio` is reused on whichever axis is active, so re-orienting keeps the
  proportion. The minimums differ by axis — **`minPaneW` 220, `minPaneH` 150**:
  220px is where the filename column stops eliding to nothing, while vertically
  a pane only has to keep a few list rows under the preview panel, whose own
  splitter already clamps itself to `view.height - 90`. `paneTrailSize` has a
  hard `Math.max(1, …)` floor: a window too small for two minimums must still
  not produce a zero-size rect, because filer feeds the vtb socket and
  hyprvtb's `renderRect` aborts the compositor on one.
- The trailing (right/bottom) pane is a `Loader`, so an unsplit window pays for
  no second listing, watch set or thumbnail queue.
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
  `split`, `splitVertical` and `splitRatio` is enough to restore the split as it
  was. A restored split points the chrome at the LEFT pane; opening one by hand
  focuses the new (right) one, because that is the pane you just asked for.
  `splitVertical` defaults to **true** in `main.py` — a `state.json` written
  before the split had an axis has no such key, and must come back as the
  side-by-side split that was then the only one.
- **A picker is never split** (`filer --pick` is one transient errand): both
  split buttons are disabled and `setSplit()` refuses.
- **The row's timestamp columns drop out, widest-first, below ~620/~470px** —
  three fixed columns in a half-width pane left the filename elided to nothing.
  They go to `width: 0`, not `visible: false`: the next column anchors to this
  one's left edge and an invisible item keeps its geometry.

Verify with `tools/split-test.py` (offscreen, ~70 checks — geometry on both
axes, which pane the chrome follows, the watch union, a real drop into the
right-hand pane, the re-orientation keeping both panes, the per-axis ratio
clamps, the zero-size guard at absurd window sizes, and the restore of an old
and a stacked `state.json`). Its stub `Titlebar` carries the real `clicked`
signal, so the button ids are exercised, not just read. It redirects `Settings`
into a temp dir, which any harness that navigates or sorts **must** do or it
rewrites where the user's own filer reopens. Any harness that loads `Main.qml`
must also set every `startSplit*` context property (`drop-test.py`,
`pick-test.py` do) — an unqualified read of a missing one is a `ReferenceError`
that takes the whole `Component.onCompleted` with it.

## The preview grid: images AND video poster frames

`preview_kind` (`main.py`) sorts every entry into `dir | image | video | file`;
`buildRows` diverts the first two at depth 0 into the pane's **`previews`**
model, which is what the grid at the top of the pane shows. (The property was
called `images` until video joined it.)

- **One provider, keyed on the PATH.** `qml/PreviewTile.qml` asks
  `image://thumb/<abs>` for both kinds and `make_thumb` works out how to make
  one, so a new previewable kind needs a branch in `_generate`, not in the QML.
- **The video poster frame is ffmpeg, seeked, and blank-rejecting.**
  `_video_frame` walks `VIDEO_SEEK_FRACTIONS` (⅓, 0.6, 0.1, 0) and takes the
  first frame that is not a flat field. `-ss` goes **before** `-i` — fast
  keyframe seek, so the cost is one keyframe rather than the file, which is what
  makes a folder of films affordable. 10% was the obvious fraction and is wrong:
  a clip with a black first second returned `#000000` for it, measured. A clip
  that is blank all the way through still gets its blank frame; the no-preview
  marker would be a lie about a file that decodes fine.
- **The oversized-source cap (`THUMB_MAX_SRC`) does NOT apply to video**, and
  must not: it exists to bound *decode* cost, and a 4 GB `.mkv` is cheaper to
  thumbnail than a 130 MB TIFF. Applying it would blank exactly the files most
  worth a poster frame.
- Results land in the **shared freedesktop cache** like every other thumbnail,
  so a warm revisit is a small PNG read and Dolphin gets the benefit too.
- `ffmpeg`/`ffprobe` are **not** in `filer.nix` — PATH-resolved via
  `notify.tool` like `kitty` and videoconv's binaries, so a machine without them
  shows the no-preview marker instead of failing to build.
- **The play marker is DRAWN, not lettered** — a seven-row staircase of
  `Rectangle`s in a `Loader`. `▶` is glyph 0 in two of the three selectable
  pixel fonts (docs/DESIGN.md §2.3), and the `Loader` keeps a still tile from
  paying for nine items it never shows.
- filer's `VIDEO_EXTS` **must equal viewer's** — filer hands these to `viewer`,
  so a mismatch is a file with a tile here and no player there. `thumb-test.py`
  asserts it.

Verify with `tools/thumb-test.py` (offscreen, ~33 checks; it generates every
clip it thumbnails with ffmpeg, so it never touches his media or his cache).

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

- **NOTHING MAY REBUILD A PANE'S MODEL WHILE A DRAG-OUT IS IN FLIGHT.** This is
  the rule the four `top` coredumps of 2026-08-03..05 bought. `Drag.active` is
  bound on the delegate, so `QQuickDragAttached::startDrag` runs `QDrag::exec()`
  — a **nested event loop** — from inside the delegate's own
  `QQuickMouseArea::mouseMoveEvent`. Timers still run in that loop, so
  `DirWatch`'s 200 ms debounce fires, `refreshAll()` reassigns
  `rows`/`previews`, and every delegate is destroyed underneath the drag. When
  the loop returns, `mouseMoveEvent` resumes on a freed MouseArea (SEGV in
  `QQuickItem::parentItem`) and the `QDrag` — which `QQuickDragAttached` parents
  to the **source item** — has been freed with it, so `QBasicDrag::eventFilter`
  `deleteLater()`s a dead object (SEGV in `lockThreadPostEventList`). Both
  signatures are in the dumps.
  - The window carries `dragInFlight` (`Main.qml`); each pane takes it as a
    property and reports its own drags back through `dragStateChanged`. It is
    per WINDOW because the source is one pane's delegate while `refreshAll` hits
    both — dragging into the other pane is exactly that case.
  - `rebuild()` is the one choke point every model reassignment goes through
    (refresh, expand/collapse, cd, sort), so the guard lives there and defers:
    `rebuildDeferred` flushes the moment the drag ends. **Deferred, never
    dropped** — a file that appeared mid-drag still has to show up.

Verify with `tools/drop-test.py` (offscreen; posts real `QDragEnter`/`QDrop`
events at the window, so the DropArea, the target hit-test and the transfer are
all exercised without a window on anyone's screen) and `tools/dragsource-test.py`
for the source half. The latter asserts the invariant rather than the crash: the
offscreen platform's `QPlatformDrag` returns without spinning `QDrag::exec()`'s
nested loop, so the use-after-free window never opens there.

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

**Run it through `portal-tests.sh`, not by hand.** The two halves need two
different interpreters and on `top` they live in two different wrappers —
PySide6 in `filer`'s, `gi` in `filer-portal`'s — and the script resolves both
(overridable: `FILER_TEST_PYTHON`, `FILER_TEST_PYTHON_GI`), falling back to
`/usr/bin/python3`, which is book's answer to both. That fallback used to be
hardcoded, so the whole suite was unrunnable on `top`, which is exactly the
pressure that ends with somebody opening a real dialog to see if it works.

## File operations REPORT — every one of them

Every `cp`/`mv`/`ln`/`rm`/`mkdir`/`gio trash` goes through `FileOps.run`
(`main.py`), and that function's contract is now **the outcome is always
visible**. It used to wire `finished` *and* `errorOccurred` to one handler that
read neither the exit code nor stderr, so a denied `rm -rf`, a cross-device
`mv`, a full disk and a successful copy were the same event on screen —
docs/DESIGN.md §10's headline rule, inverted, in the one app whose mistakes are other
people's files. Four distinctions the fix keeps apart, and none of them may be
collapsed again:

- **failed vs succeeded** — non-zero exit raises a critical toast carrying the
  helper's *own* stderr, which already names the file and the reason
  (`cp: cannot create regular file 'x': Permission denied`). Never paraphrase
  it; coreutils says it better and says it about the right file.
- **failed vs could not be started** — `errorOccurred(FailedToStart)` means the
  binary is missing from filer's PATH. Different sentence (`cannot run gio`),
  different fix — a `filer.nix` change, not a permissions problem.
- **partial vs total** — one pasted item is one process, so a ten-item paste is
  ten exit codes. `runPaste` wraps the loop in `FileOps.beginBatch(label)` /
  `endBatch(tok)` and passes the token as `run`'s third argument; three failures
  then read `copy: 3 of 10 failed`, once, with the first three reasons.
  **`endBatch` is mandatory** — without it the failures are collected and never
  reported. Anything that adds a new multi-process loop must do the same.
- **failed vs declined** — the no-clobber flags (`cp -an`, `mv -n`) exit **0**
  when they skip, so the overwrite-confirm flow above them is untouched: a
  conflict is still a dialog, never a toast.

`finished(reselect)` fires either way, because a partly-failed batch still
changed the disk and the view must show what is actually there. The label in a
message is *derived* from the argv (`_op_label`) rather than passed in, so a
call site cannot forget it — including `mv` within one directory, which is
called `rename`, not `move`. `execDetached` has no exit code to read, but a
launch that could not start is knowable and is toasted too (§10's "an action
`execDetached` cannot report on must not be OFFERED").

**The toast is `notify.py`, filer's one toast path** — `tool()` (profile-dir
binary resolution) plus `toast()` (`notify-send`, `--replace-id`, `-t 0` for an
ongoing job). It was extracted from `videoconv.py`, which now calls it, so there
is one implementation of how a filer toast is spelled rather than two.

Verify with `tools/fileop-test.py` (offscreen, ~44 checks). It injects *real*
failures — a chmod 500 directory, a root-owned destination, a source that does
not exist, a genuine ENOSPC by writing to `/dev/full`, a binary that is not
installed — and asserts the exact title and body of each toast, that a batch
reports once with an honest count, that a no-clobber skip is silent, and that
the real `Main.qml`'s `transferInto` reports through the same path. **The toast
is stubbed** (`main.toast` is swapped for a collector): a test must never put
notifications on the user's screen, and the assertions need the exact strings.

> The bug this fixed had hidden a second one for filer's whole life: **`gio` was
> on no PATH the app could see**, so *trash* — the safe default delete, on the
> titlebar and in the context menu — did nothing at all, silently, while the
> selection cleared and the list refreshed. `home/prog/filer.nix` now prefixes
> `glib`'s bin dir onto the wrapper's PATH. Silence is what let it rot.

- **`videoconv.py`** — the context menu's video actions: two upload-limit
  squeezes, "compress to <10MB" and "compress to <4MB", plus "copy without
  audio". Exposed as the
  `VideoConv` context property; the only part of filer
  that shells out to `ffmpeg`/`ffprobe` (PATH-resolved through `notify.tool`,
  like `kitty` — nothing was added to `filer.nix` for those, so a missing tool
  surfaces as a failure toast, not a broken build; `gio` is the one exception,
  see above).
  - **The ceiling is a PARAMETER, not two code paths.** `limit` (bytes) is
    threaded through `plan(path, size, limit)`, `out_path_for(src, limit)` and
    the `plan`/`start` slots — both of which QML calls with two arguments and
    both of which still answer a one-argument call with `LIMIT` — so the sizing
    model, the ladder, the refusals and the corrective pass are one
    implementation. `LIMITS` is the tuple the menu offers; adding a third row
    is a label and a number, and `label(limit)` spells it (`"4MB"`) for the
    menu, the toasts and every refusal. The tag lands in the output name, so
    the two squeezes of one clip are `clip-10mb.mp4` and `clip-4mb.mp4` rather
    than one overwriting the other.
  - **One compression per source, whichever ceiling.** The job key stays
    `compress:<src>` — a second encode of the same file is the same decode
    again for a smaller version of what the first is already producing — so
    the second click is refused with "already compressing that file".
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
  - The output is verified against its own ceiling after the encode; one
    corrective pass runs if it somehow overshot.
  - **"copy without audio" (`stripAudio`) is a stream copy, and that is the
    whole design.** `-map 0 -map -0:a -c copy -dn`: everything but the audio is
    copied bit-for-bit, so it runs at IO speed and the video is the *same*
    video, not a generation-loss copy of it (`tools/strip-audio-test.py` hashes
    the video bitstream to hold that). Consequences: the output **keeps the
    source's container/extension** (`clip.mkv` -> `clip-muted.mkv`), unlike the
    compressor's always-mp4; there is no `plan()`, no dialog and no quality
    decision to make; and a container that refuses one of the copied
    subtitle/attachment streams gets one silent retry with the video alone.
  - It has **no menu-time probe**: the row appears for every video, and a file
    with no audio track is refused with a toast when clicked. An ffprobe per
    right-click would be the alternative, and a silent `-muted` duplicate the
    worse one.
  - The job table is keyed **`<kind>:<src>`**, so compressing a file and
    stripping its audio are not each other's "already running".

## "send to phone" — KDE Connect, in the file context menu

`phone.py` + `sendToPhoneItems()`/`sendToPhone()` in `qml/BrowserPane.qml`. It
sits with `open` / `open with...` / `compress to <10MB` / `compress to <4MB` /
`copy without audio`, before the first
separator: nothing about it is destructive and it must not be next to `trash`.

- **One row per device, named after the device.** `CtxMenu` has no submenus, and
  with one or two phones paired a flat row each is shorter to reach *and* says
  where the file is going. The devices are enumerated **as the menu is built** —
  `Phone.devices()` is a fresh `kdeconnect-cli --list-available --id-name-only`,
  ~10ms measured on `top` — never once at startup: a phone that left wifi has to
  leave the menu, not linger as a row that fails.
- **The two empty cases are greyed and SAY WHICH** (docs/DESIGN.md §10): `send to
  phone - no device reachable` when nothing is paired-and-reachable, `send to
  phone - directories cannot be sent` when the selection holds no file. Every
  way `devices()` can go wrong — no daemon, no binary, non-zero exit, timeout,
  an unparseable line — collapses to *no devices*, which is the greyed row. A
  half-parsed device would be a row that quietly fails, which is the thing the
  rule forbids.
- **Directories are counted out of the label, not failed afterwards.**
  `--share` takes a file, so `Phone.sendable()` filters, and a selection of five
  files and a folder reads `(5)` and sends five.
- **The send is `FileOps.run`, in a `beginBatch`/`endBatch`** — one process per
  file, so it reports exactly as a multi-item paste does: `send to phone: 3 of
  10 failed`, once. `_op_label` maps `kdeconnect-cli` to `send to phone` so a
  standalone run is not named after the binary either.
- **PACKAGING: nothing was added to `filer.nix` and nothing needs to be.**
  `kdeconnect-cli` comes from `kdeconnect-kde` in `home/pkgs/desktop/kde.nix`,
  which is ungated, so **both** `top` and `book` get it, and `notify.tool`'s
  profile-dir fallback resolves it on each (`/etc/profiles/per-user/lam/bin` on
  `top`, `~/.nix-profile/bin` on `book`, which the graphical session's PATH does
  not carry there). On `book` the entry simply greys out whenever Fedora's
  `kdeconnectd` is not running — which is the honest answer, not a bug.

Verify with `tools/phone-test.py` (offscreen, ~38 checks). `Phone.devices` is
scripted and `FileOps` is a collector: it asserts the exact labels and enabled
flags for none/one/two devices, that the count is the *sendable* count, that a
row's own JS closure runs one `kdeconnect-cli -d <id> --share <file>` per file
inside one batch, and where the entry lands relative to the separators.
**It never runs the real binary and never sends anything to a real device.**

## `:top` in the address bar — browsing the other machine

Type `:top` into the path bar and filer shows lam's home on `top`. It is an
sshfs mount and a name rewrite, and everything else in the app is untouched:
by the time the tree, the preview grid, drag and drop, a copy or `viewer` sees
a path, it is an ordinary local path under the mountpoint. `remote.py` is the
whole feature; its docstring is the reference and this is what an agent needs
before changing it.

- **The mount is the remote's `/`, one per host**, at
  `$XDG_RUNTIME_DIR/filer-remote/<user>@<host>`. Mounting the *home* instead
  would need a mountpoint per (host, root) pair — `:top` and `:top:/etc` would
  collide on one directory — and would make the reverse map ambiguous. Rooting
  at `/` makes the rewrite a plain prefix swap, keeps `^` walking out of the
  home the way it does locally, and puts the mount in a directory a logout
  takes away with it.
- **`pretty()` and `parse()` are inverses, and that is load-bearing.** The
  window title *is* the editable address bar, so it shows `:top/dl` rather
  than the runtime-dir mountpoint — and pressing Enter on that text unchanged
  must land where it already is. `tools/remote-test.py` asserts the round trip
  for every shape (home, subpath, explicit `:host:/abs`, non-default user, and
  the `/home/lambda` near-miss that must NOT be read as a subpath of
  `/home/lam`). It is offline: nothing mounts, connects or resolves a name.
- **Mounting is off the GUI thread**, because an ssh handshake to a sleeping
  machine takes as long as `ConnectTimeout`. `Remote.open()` returns at once;
  `Main.qml` remembers *which pane asked* (not `focusPane` — a click in the
  other half mid-connect must not redirect the navigation) and navigates on
  `ready`. A failure toasts the reason ssh gave and moves nothing: this is the
  "never let an action fail silently" rule (docs/DESIGN.md 10.4), and the path
  bar sitting on the old directory with no explanation is exactly what it
  forbids.
- **An address naming this machine needs no mount** — `:book` on book is just
  `/home/lam`, resolved locally.
- **A false positive in `parse()` costs a local directory.** Anything it
  claims stops being treated as a path, so the "must stay local" half of
  `remote-test.py` matters as much as the accepting half.
- **Auth is keys only** (`BatchMode=yes`): there is no terminal for a
  passphrase prompt, and without it a mount hangs until the timeout. Unknown
  host keys are taken on first use (`accept-new`), the same answer a person
  gives the interactive prompt. `reconnect` + keepalives are set so a laptop
  that slept comes back instead of leaving a wedged mountpoint; `_live()`
  checks a mount is actually readable rather than trusting `ismount`, because
  a dropped sshfs leaves the mountpoint standing with every call on it
  returning `ENOTCONN`.
- **PACKAGING differs per host.** `top` gets `pkgs.sshfs` on the wrapper's
  PATH in `home/prog/filer.nix` (like `gio`: `home.packages` is not enough for
  an app launched from a .desktop entry). `book` needs nothing from this repo
  — it runs Fedora's python3 with `/usr/sbin/sshfs` on PATH, and nixpkgs'
  sshfs would be the *wrong* one there, its libfuse looking for the setuid
  `fusermount3` in `/run/wrappers/bin`, which exists only on NixOS. Both are
  resolved through `notify.tool()`, which is why that function's fallback list
  grew `/run/wrappers/bin` and `/usr/sbin`.
- **What works today, in each direction.** `:top` from `book` works over the
  LAN now and over the tailnet once both nodes are joined — `top` is the same
  name either way (MagicDNS), which is why the address is a bare hostname and
  not an address. `:book` from `top` does NOT: book runs no sshd. That is
  Fedora state this repo cannot declare (`systemctl enable --now sshd` there);
  until then the address fails with a "cannot reach book / connection refused"
  toast, which is the honest answer.
### Why it is as fast as it is — measure before you retune

All numbers book -> top, 5 GHz wifi, 7 ms RTT. **The link is the ceiling**: raw
ssh moves 39 MB/s and every cipher measures the same (39-40 MB/s for chacha20,
aes128-gcm, aes256-gcm, aes128-ctr), so nothing is to be won by changing
ciphers, and a single sshfs stream at 30 MB/s was already at 77% of it.
Directory metadata is not the problem either — 1191 entries list in 0.11s cold
and 0.04s cached, and stat-ing all of them costs 0.06s.

What actually moved the needle, and what each is worth:

- **`auto_cache` — the big one.** Without it a re-read is the full transfer
  again, and re-reading is the normal case: the preview grid thumbnails an
  image, you click it, viewer reads the same bytes. Measured on a 12 MB image,
  thumbnail-read then click-read: **0.40s + 0.38s before, 0.41s + 0.011s
  after**. On an 87 MB PNG: 2.94s + 2.94s before, 2.93s + 0.066s after.
  Not `kernel_cache`, which never revalidates; `auto_cache` checks size and
  mtime. Its one hole, measured: a remote file rewritten to the *same byte
  length* inside `cache_timeout` is served stale. A size change is seen at once.
- **`max_conns=4`.** One connection is one stream, so the thumbnail pool's four
  workers shared 30 MB/s. Four connections reach **37 MB/s** — the link's own
  ceiling — and cost a single stream nothing.
- **`cache_timeout` 20 -> 5.** With `auto_cache` the attribute cache also bounds
  how long stale *content* can be served, and listings are cheap enough (above)
  that revalidating four times as often is not perceptible.
- **`Remote.prefetch()`, called from `openFile` before the app is launched.**
  viewer needs 0.22s to stand its QML up and only then reads the file; starting
  the transfer at click time instead means it overlaps that. Measured on cold
  6-9 MB images, viewer's own wait: **0.224s -> 0.048s mean**, click-to-shown
  0.42s -> 0.27s. It only works *because* of `auto_cache` — without it the
  second reader pays the full transfer again and the prefetch is a pure loss.
  Capped at `PREFETCH_MAX` so clicking a 4 GB video does not try to haul it.
- **Measured and NOT adopted:** bigger `max_read`/readahead (no change, 28-30
  MB/s either way); `kernel_cache` (same speed as `auto_cache`, no
  revalidation).

**Still on the table, measured, not built: thumbnailing on the remote side.**
`ssh top magick <file> -thumbnail 256x256 png:-` over a multiplexed connection
costs 0.15s for a 330 KB jpeg and **1.9s for an 87 MB PNG, versus ~3.5s to pull
and decode it locally** — so it wins above roughly 4 MB and loses below it,
which makes it a size-thresholded path, not a replacement. The prize is the
whole-folder case: `~/Pictures` on top is 1191 files and **4.4 GB**, average 3.8
MB, and scrolling the grid pulls all of it; remote thumbnails would make that
~36 MB. `magick` and `ffmpeg` are both already on top. Nothing of this is
implemented.

**And the thing that actually made a click feel quick, which was none of the
above.** Measured after all of it: a 1.25 MB image over the mount was 0.04-0.12s
of transfer against **0.23s of viewer's own startup** — python + PySide6 + the
QML engine — so ~85% of the wait was starting a process and the network work is
invisible on a normal image. `openFile` now offers the job to a viewer that is
already open (`FileOps.handOff` -> `pylib/handoff.py`), which costs **0.7ms**,
and only launches one when nobody takes it. Shift-click forces a new window.
The full rationale is in [`../viewer/AGENTS.md`](../viewer/AGENTS.md); the rule
that keeps it honest is that a viewer nobody can see refuses, so a click can
never go nowhere.

- **Two sshfs properties, not filer bugs**: a remote directory's thumbnails
  pull the files over the wire, and a remote symlink to an absolute path
  (`/nix/store/...`) resolves against THIS machine's copy of that path,
  because the link text crosses untranslated.

## "copy under 4MB" — the stills half of videoconv

`imgconv.py`, and it is deliberately the same shape as `videoconv.py`: a
right-click on an image too big for wherever you are about to paste it, a copy
**beside the original** (`photo.png` -> `photo-4mb.jpg`, never clobbering), a
desktop toast, and `finished(outPath)` so the view lands the selection on the
new file. No dialog and no questions — a still needs no ffprobe, no encoder
choice and no progress stream, so this one is a fraction of its sibling's size.

**The SEARCH is `pylib/imgfit.py` now** (2026-08-06), not this file: painter
needed the same budget for the collage it hands to a drag, and a second copy of
a quality search is how two apps end up disagreeing about what "4MB" means.
`imgconv.py` keeps what is filer's — the copy named beside the original, the
toast, the QObject the menu talks to — and the old private names
(`_uses_alpha`, `_encode`, `_best_under`) are aliases onto it so this guide's
citations and the harness still hold. Everything below describes that search and
still applies.

- **Quality first, then resolution.** A lower JPEG quality costs detail you
  have to look for; discarding pixels costs detail that is simply gone. So each
  rung of `SCALES` gets a binary search over quality (~5 encodes), and the next
  smaller rung is only reached when even `Q_MIN` will not fit there. An image
  barely over the line therefore comes back **full resolution** — measured, a
  6.6 MB source lands at 1.06 MB, q=92, 2642x1270, in 0.2s — and only a
  genuinely huge one is scaled.
- **Everything is measured by encoding into a `QBuffer`**, never by writing and
  stat-ing. Construct it as `QBuffer()`, using its own internal array: handing
  it a `QByteArray()` makes it borrow a Python-owned temporary that is collected
  while the JPEG writer is still filling it — a hard SEGV inside
  `QBuffer::writeData`, on the first encode, every time.
- **JPEG, unless the alpha is actually used.** A PNG from almost any tool
  carries an alpha channel that is opaque everywhere, so `hasAlphaChannel()`
  would send the common case to WebP for nothing; `_uses_alpha()` samples a
  64x64 reduction instead. A source that IS transparent becomes lossy WebP,
  which keeps it — flattening onto an invented background would be a silent
  wrong answer.
- **The menu entry is only offered when it can work**: `kind === "image"` and
  `size > 4000000`, both already in the model, so it costs no stat and no
  decode per right-click. Everything else is refused out loud with a reason —
  an animation (one frame of a GIF is not a copy of it), an undecodable file,
  a budget nothing can meet.
- **Qt's 256 MB decode ceiling is raised, process-wide, from here.** Any image
  whose uncompressed form exceeds it fails with the thoroughly misleading
  "Unable to read image data" — so the images most worth shrinking were exactly
  the ones that silently could not be. Measured on a 9000x8113 PNG from top (73
  MP, 292 MB as ARGB32): refused before, and 82.9M -> 3.5M at full resolution
  in 2.0s after. **It fixed the preview grid too** — that same PNG got no
  thumbnail tile at all for the same reason, verified both ways at 256 MB and
  at the new limit. `MAX_SRC_PIXELS` is the real guard; the allocation limit is
  set to exactly what that allows.

Verify with `tools/imgconv-test.py` (offscreen, ~21 checks, self-contained). It
generates its own noise sources — a gradient would fit the budget at any
quality and prove nothing — and asserts the copy is under the limit AND
decodable, that quality is spent before pixels, that transparency survives as
WebP while an opaque ARGB image does not, that a second run does not clobber
the first, and each refusal. The animated-GIF case builds a real 60-frame gif
with ffmpeg and skips out loud without it: a hand-assembled two-frame gif was
tried first and Qt's reader reported `imageCount() == 1` for it, so the harness
quietly skipped the one refusal it existed to check.
