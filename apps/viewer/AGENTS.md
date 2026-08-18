# `viewer` — image viewer

Vendored source of the standalone image viewer (its own self-contained flake —
`main.py`, `qml/`). Built/installed by `home/prog/viewer.nix`, which mirrors
`filer.nix` exactly, including the `air` system-python split; it runs the
**live** source at `/home/lam/nix/apps/viewer/main.py`, so edits need no
rebuild. See [`../AGENTS.md`](../AGENTS.md) for the shared rules.

- **Split out of filer's old built-in overlay.** filer's `openFile` now shells
  out to `viewer <path>`, and viewer scans that file's directory for the sibling
  images, so ‹/› flip through the folder.
- **`--order FILE` overrides that scan** with the caller's own order: NUL-
  separated paths (a filename may contain a newline), non-media entries and
  directories dropped viewer-side so the caller needn't know what viewer
  decodes. filer passes it on every image open (`FileOps.writeOrder` →
  `orderPaths()`), so ‹/› follow the sort the user is actually looking at
  instead of viewer's own name-sort — sort filer by size and viewer flips by
  size. viewer **consumes** the file (unlinks it, temp roots only) and nothing
  watches it: the order is a launch-time snapshot, so re-sorting filer while a
  viewer is open leaves that viewer alone, by design. Falls back to the plain
  scan if the file is unreadable or doesn't contain the opened path.
- **`--select-back <sock>:<pane>` is the way back**: every time the focused pane
  lands on a different image, viewer echoes that path at filer's socket and
  filer selects it (`FilerLink`, main.py). So flipping through a folder here and
  closing the window leaves filer on the picture you stopped at. The opposite of
  `--order` in lifetime, on purpose — that is a launch-time snapshot, this is a
  live link for as long as the window is open. It is **debounced** (120ms):
  holding › walks the folder as fast as it decodes and each echo is a
  synchronous round trip on the GUI thread, while what filer needs is where you
  came to rest. A handoff **re-points** it, so a second filer's click is not
  reported to the first one, and `viewer x.png` from a terminal echoes nowhere.
  The path it reports comes off `ImageViewer.path` rather than
  `images[paneIdx()]`: a pane's position is a ListModel role, and a binding over
  `panes.get()` is not one you can trust to re-run. Harness
  `tools/select-back-test.py`; filer's half is
  `../filer/tools/viewer-select-test.py`.
- Its prev/next/zoom/fit/close controls live in the **hyprvtb titlebar** (the
  same `pylib/vtbclient.py` bridge filer/surfer use), not in QML.

## Split view — a GRID of panes, each its own drop target

`sp` adds a pane, `xp` closes the focused one, up to `MAX_PANES` (9). Modelled
on surfer's two-pane split and sharing its vocabulary (`focusPane`, a 1px accent
frame on the focused pane, a draggable divider whose position is persisted on
RELEASE of the drag) — but generalised, because "view a bunch of images at the
same time" is not two.

- **The layout is `cols = ceil(sqrt(n))`, `rows = ceil(n/cols)`.** 2 panes are
  side by side, 4 are a 2x2, 9 are a 3x3. A short last row has its final pane
  **span the leftover columns**, so 3 panes are one wide over two, never a hole.
- **One shared `images` list, one position per pane.** ‹ / › move the focused
  pane only. A new pane opens on the image after the last one already shown, so
  splitting twice walks forward instead of showing one picture three times.
- **Every pane is its own `DropArea`.** Drag images out of filer (or anything
  offering local file URLs) onto the pane that should show them. Unknown paths
  are **appended** to `images` rather than replacing it, so ‹ / › can still walk
  back to what was open; a path already in the list reuses its slot. A drop of
  several files fills the pane it landed on and **opens new panes for the rest**
  — never overwriting panes the user has arranged. `Files.mediaEntries`
  (main.py) decodes the uri-list with `QUrl`, the same rule as filer's
  `FileOps.uriList`/`urlsToPaths`: **never decode a uri-list in QML**, because
  `encodeURI`/`decodeURI` leave `#` and `?` mangled — that was a real filer bug.
  Non-media and non-local drops are declined, so the source shows a refused drop
  instead of a silent no-op.
- **No pane ever takes Qt's active focus.** The keys live on `stage`, the single
  item that holds the window's focus, and every one of them acts on `focusPane`.
  That is deliberate: surfer's split had to add a `retargeting` flag because Qt
  hands a hidden view's focus to the other pane, indistinguishable from a click
  there. With N panes that fight would be worse, so there is nothing to fight
  over — a pane is focused by clicking it, zooming over it, dropping on it, or
  Tab / Ctrl+1..9.
- **Divider weights, not pixels**, persisted per grid **shape** (`Prefs`
  `paneWeights: {"2x1": {col, row}}` in `$XDG_CONFIG_HOME/viewer/prefs.json`) —
  a 2x2's dividers say nothing about a 3x1's, and viewer reshapes on every
  add/close. `reshape()` hangs off `shapeKey`, **not** off `cols`/`rows`: those
  settle one at a time, so a handler on either runs only for shapes that never
  exist (1 pane → 2 fired for "1x2" and "2x2", never "2x1") and the saved
  divider was silently never restored.
- `viewer --split a.png b.png c.png` opens one pane per path. It is a flag, not
  the default, because several paths have always meant "flip through exactly
  these" and filer relies on that. `--order` is unaffected — it is still a
  single-pane, launch-time snapshot.
- Only the **focused** pane's video is audible (`AudioOutput.muted`); four clips
  at once would otherwise be four soundtracks, and the titlebar can pause one.

## Compare — a before/after reveal slider (`--compare`)

`viewer --compare <before> <after>` opens straight into a two-image comparison
instead of the pane grid: the two images (assumed the SAME dimensions — a
model's input and its output) are overlaid, and a vertical reveal line **follows
the mouse** — `before` shows to the LEFT of the line, `after` to the RIGHT, and
the line tracks the pointer's x exactly as it moves. No clicking. This is
painter's contract — it drives exactly this invocation, so the flag name and the
argument order (before first, after second) are fixed.

- **The reveal is a CLIP, never a rescale** (`qml/CompareView.qml`). Both images
  draw at the full window size with `PreserveAspectFit`, so a same-size pair
  letterboxes identically and lines up pixel-for-pixel; the `before` image sits
  inside a clip box pinned at `x:0` whose width is the reveal point, so moving
  the line changes only what shows of it, never how big it is drawn.
- **The line tracks the pointer 1:1, zero easing** (docs/DESIGN.md §6.4, §6.11).
  A hover `MouseArea` with `acceptedButtons: Qt.NoButton` writes `trackX` straight
  from `positionChanged` — nothing is clicked, nothing is smoothed. `splitX` is a
  pure binding (`tracked ? trackX : width/2`): centred until the pointer first
  enters, then following it, with the centring binding never broken by an
  imperative write.
- **It is its own window, always.** `--compare` skips the running-viewer handoff
  (like `--new-window`), so painter always gets a fresh comparison rather than
  the image landing in an unrelated viewer's pane grid. `split_args` consumes the
  two paths so they are not treated as an ordinary flip list, and Main.qml builds
  no panes, no dividers, no focus frame and no flip/zoom/split titlebar buttons
  when `compare` is set — a comparison is one surface, not N panes. `q`/Escape
  still quit.

Verify with `tools/compare-test.py` (offscreen): the argv contract, the two
paths landing as before/after, the pointer-tracking, the clip geometry, the
clamp, the empty chrome and the quit. Run it the same way `split-test.py` is
(below) — it reuses that file's `build()`/`spin()`/`png()`.

## Right-click → "copy image"

viewer's only context menu, one row, on whichever pane the click landed in
(which the same tap focuses, so the row acts on what the chrome says it does).
`qml/CtxMenu.qml` is the desktop's verbatim copy — see [`../AGENTS.md`](../AGENTS.md),
and retune all eight or none.

- **The copy is `pylib/clipfile.py`, never `QClipboard`** (`Clip` in `main.py`).
  A Wayland selection dies with the process that offered it, so a copy made in
  Qt would stop being pasteable the moment the viewer closed — the one thing a
  copy must not do. clipfile forks a holder that outlives us. `QClipboard`
  additionally SIGSEGVs PySide on exit; the whole argument is in `../AGENTS.md`
  → `pylib/`.
- **An image is offered BOTH ways**, via clipfile's `--image`: as a file (name
  and all — an upload field, a chat client) and as its own image mime (an
  editor, a canvas). No conversion, so a JPEG goes on as `image/jpeg` and a
  consumer that will only take `image/png` gets the file paste instead.
- **A video says "copy file"**, because there is no picture to hand over and a
  row labelled "copy image" that pasted a path would be a lie.
- **The outcome goes to the titlebar FOOTER** — `win.flash()`, 2.5s for a
  success and 5s for a failure, carrying clipfile's own last stderr line. The
  footer and not a desktop toast: it is already viewer's one status surface,
  and a notification server is one more thing that can be absent. A copy that
  silently did nothing would look exactly like one that worked, right up until
  the paste (docs/DESIGN.md §10).

Verify with `tools/copy-test.py` (offscreen, 15 checks): it posts a real
right-click at a pane, clicks the row that comes up, and asserts the argv, the
footer text and each refusal. **It cannot touch his clipboard** — `CLIPFILE` is
repointed at a stub that records argv and exits with a chosen code, so nothing
in it speaks the data-control protocol. That clipfile really owns the selection
and offers what it claims is `apps/pylib/tools/clipfile-test.sh`, in a headless
sway of its own. Run both the way `split-test.py` is run (below).

## Video: nothing plays until the window has appeared, and `mu` is remembered

- **The reveal gate.** hyprvtb shows a freshly-mapped window in two beats — the
  titlebar fades in (`VTB_FADE_DURATION`, 160ms in `vtbDeco.cpp`), then the
  window rolls out from behind it (`plugin:hyprvtb:slide_duration_ms`). A clip
  used to autoplay at map time, so it was most of a second in — audio and all —
  behind a window still unrolling. `Main.qml`'s `revealed` (a one-shot timer of
  `motion.slideMs + 160`) gates `ImageViewer.canPlay`, and the false→true edge
  starts whatever was waiting.
  - **Deliberately not `motion.ms()`**: that scales by the panel's `animSpeed`
    and returns 0 under `reduceMotion`, and what is being waited on is the
    COMPOSITOR's animation, which neither setting touches. `slideMs` is still
    hyprvtb's published number (`qmlcommon/Motion.qml`), so retuning the key
    moves this with it.
  - It is **once per window**, so a handoff into an already-open viewer
    (`openSet`) plays immediately — there is no reveal to wait for.
- **`mu` in the inner titlebar** toggles mute, lit when muted (docs/DESIGN.md
  §12.1 — an active toggle inverts), offered only on a video. It is the
  WINDOW's, not a pane's: the panes already mute themselves when unfocused, and
  a per-pane mute would give four answers to "is this window making noise".
  `AudioOutput.muted` is `!paneFocused || appMuted`.
- **It outlives the window** — `Prefs.muted` in
  `$XDG_CONFIG_HOME/viewer/prefs.json`, beside the divider weights. A mute is a
  preference about this machine's speakers, not about one clip.

Verify with `tools/video-test.py` (offscreen, 21 checks). **The clip it builds
has no audio track on purpose**: the run must not be able to make a sound on his
speakers even if a decoder starts, so muting is asserted on
`ImageViewer.silent`, never by listening. It reads the pane through a
`QQmlExpression` in the window's scope — `win.current` is a `QQuickItem*` PySide
cannot convert, and a Repeater's delegates are not QObject-children of the
window — and presses the titlebar button through the stub's real `clicked`
signal, so `Main.qml`'s own `Connections` are what run.

## Video decodes on NVDEC, never VAAPI (`top`)

`home/prog/viewer.nix` sets `QT_FFMPEG_DECODING_HW_DEVICE_TYPES=cuda` on the
NVIDIA host, and that is not a tuning knob — it is the fix for two coredumps
(2026-07-30 and 2026-08-03, a `.webm` each).

Qt's ffmpeg backend probes hardware decoders in its own order and takes **VAAPI**
first. The VAAPI provider on `top`'s default render node (`/dev/dri/renderD128`)
is NVIDIA's own shim, `nvidia_drv_video.so`, and it cannot export a surface as a
DRM-prime handle at all: measured on the sandbox monitor 2026-08-05,
`vaExportSurfaceHandle failed` **202 times in 9 s** for a VP9 clip and 392 for a
VP8 one — every frame. Qt then falls back to a per-frame CPU transfer, which is
both why video played badly *and* how viewer died:
`av_hwframe_transfer_data` → `vaapi_transfer_data_from` → `av_image_copy` hits an
`av_assert0` on a plane-size mismatch and `abort()`s, in the render thread or the
GUI thread depending on where the upload ran.

`cuda` is real NVDEC and logs zero export failures on the same clips. Qt falls
back to software on its own for anything NVDEC cannot decode, so this **narrows**
the probe order rather than forcing a decoder. It is `--set-default`, so
`QT_FFMPEG_DECODING_HW_DEVICE_TYPES= viewer x.webm` still bisects it by hand —
that env var is the first thing to reach for if video misbehaves again. `book` is
not NVIDIA and keeps Qt's default.

**Keys**: ‹ / › flip · Space play/next · `+` `-` `0` zoom/fit (with or without
Ctrl) · Ctrl+wheel or plain wheel zooms the pane under the cursor · `\` add pane
· Ctrl+W close pane (quits on the last one) · Escape or `q` quit · Tab /
Shift+Tab · Ctrl+1..9.

**Quitting goes through the compositor, not `Qt.quit()`.** `win.quit()` asks
hyprvtb to close this window with the same roll-up + fade the titlebar `[x]`
runs (`Titlebar.requestClose` → `pylib/vtbclient.close_animated()` →
`hl.plugin.hyprvtb.close_pid(<pid>)`, see `home/prog/AGENTS.md`), and the
`sendClose()` that ends the animation arrives as the ordinary close `onClosing`
already quits on. `Qt.quit()` tears the surface down where it stands, so all
Hyprland had left to animate was a fade of the last frame — the key looked
visibly different from the button beside it. It falls back to `Qt.quit()`
whenever the compositor declines (an offscreen harness, an unloaded plugin) and
a 1200 ms timer quits anyway if the close never comes: a quit key that leaves
the window standing is worse than an unanimated one.
**Right-click** copies the image (above).

Verified by **[`tools/split-test.py`](tools/split-test.py)** — offscreen, scratch
`XDG_CONFIG_HOME`, real `QDragEnter`/`QDrop` and key events posted at the real
`qml/Main.qml`; 44 checks covering pane layout, the spanning last pane, drop
routing to the pane under the cursor, the multi-file fan-out, the pane cap, the
divider clamp, the persisted weights and the quit keys — that last section is
last on purpose, since `Qt.quit()` reaches `QCoreApplication::quit` through
`QQmlApplicationEngine`'s own connection and what it asserts is the engine's
`quit` signal. Re-run it after touching the split
block; the *appearance* is the user's visual check. Run it with viewer's own Qt
env, not the bare system python:

```bash
W=$(readlink -f "$(which viewer)"); sed '$d' "$W" > /tmp/vwrenv.sh
( . /tmp/vwrenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3')" \
    apps/viewer/tools/split-test.py )
```
- **The wheel ZOOMS, and it is the one sanctioned bare `Flickable` in `apps/`**
  (now one per pane).
  `ImageViewer.qml`'s `WheelHandler` is delta-proportional — `exp(ln1.2/120·d)`,
  so one classic detent is still exactly x1.2 while a trackpad burst no longer
  slams the 1..8 range shut in a dozen events — and it consumes EVERY wheel
  event (all modifiers), so the Flickable underneath never gets one to flick
  with. That is why viewer is off `kinetic_deny_classes`: a compositor coast
  just keeps zooming smoothly and the clamp holds. Its `interactive: true` buys
  drag-panning only. Everything ELSE in `apps/` must use `../qmlcommon/`'s
  `Kinetic*` views — see [`../AGENTS.md`](../AGENTS.md).

## One viewer, reused — a click should not start a process

Opening an image from filer used to cost ~0.5s, and almost none of it was the
image: measured on book, the file was 0.04s and the rest was a fresh python +
PySide6 + QML engine + GL context. So the common case no longer starts one.

- **filer speaks the socket directly** (`FileOps.handOff`), because filer is
  already running — a click on an image that a live viewer takes costs **0.7ms**
  instead of ~500ms. A `viewer` started from anywhere else (a terminal,
  another app) does the same thing itself, at the very top of `main.py`
  **above the PySide6 imports** — those imports are 0.10s and the whole point
  is not to spend them. Protocol and rationale: `../pylib/handoff.py`.
- **The rule for taking a request is `win.isExposed()`, and nothing else.**
  A window on another workspace, rolled up or minimised gets no frame callbacks,
  so `isExposed()` is false — and loading an image into one would make the click
  do nothing at all. It refuses, filer launches a window where the person
  actually is, and the old behaviour is what you get. *This is the one
  assumption not verified on the live session* (checking it means switching his
  workspace); if a compositor ever reports a hidden window as exposed, the
  symptom is an image opening out of sight rather than in a new window.
- **`openSet()` (qml/Main.qml) is the swap**: the focused pane goes to the
  requested image, every other pane is KEPT and clamped into the new list — a
  split the user arranged must not be torn down because one image was opened
  into it — then `raise()` + `requestActivate()`.
- **`--new-window` skips the ask entirely**, and is what filer sends on a
  shift-click (`BrowserPane.openFile`'s `mods`). It is consumed in
  `split_args()`, which matters: everything not recognised there is treated as
  a path to open, so a flag that fell through would be "opened" as a file.
- An instance that finds the socket already claimed simply does not listen.
  First one in owns it; see the `removeServer()` note in `../AGENTS.md`.

Verify with `tools/handoff-test.py` (offscreen, 12 checks: the swap, the
refusal, `--order` over a handoff, caller-relative paths, an unopenable
request, and the flag). It points `$XDG_RUNTIME_DIR` at a temp directory before
importing anything, so it cannot touch the socket of the viewer the user has
open. It reuses `split-test.py`'s `build()`, which is why that file grew an
`if __name__ == "__main__"` guard.

## Never stat per entry — it is invisible locally and it is the whole latency

Opening an image from filer on a folder that lives on `top` took **4.07s to the
first frame, 3.70s of it inside `images_for()`**, and the same click on a local
folder was instant. `order_from()` was calling `os.path.isfile()` on every path
in filer's order file — one round trip each over sshfs, 891 files, 890 of which
nobody had asked to see. `feh` on the same files was immediate, which is the
tell: nothing about showing one image is slow. It is now **0.26s**.

- **A path list from a caller is trusted.** filer builds it from a directory it
  has just listed; re-checking each entry buys almost nothing and costs O(n)
  round trips. `is_media()` is a string test and stays. A path that really has
  gone shows as a broken image if you flip to it — rare, visible, honest.
- **filer excludes directories from the order file** (`orderPaths`), which is
  what makes dropping the stat safe: extension filtering alone would let a
  directory named `stuff.png` through.
- **The rule generalises: nothing on an open path may do per-file I/O.** A
  directory scan is ONE call (`os.scandir` carries the type, so `e.is_file()`
  is free); a loop of `os.path.isfile` / `os.stat` / `os.path.exists` over a
  listing is n. Locally the difference is microseconds and you will not see it
  in any test on a temp directory — which is exactly how this survived.

Guard: `tools/order-test.py`. It **counts filesystem calls** rather than
timing anything, because a timing assertion on a local temp dir passes happily
with the bug back in; it requires the count not to grow with the number of
entries (measured: 4 calls for 400 entries, 804 with the stat restored). It
also pins the rest of the contract that makes the trust safe — extension
filtering, the file being consumed, and a list not containing the clicked file
still being rejected.
