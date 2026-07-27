# AGENTS.md — the Quickshell panel

The desktop shell's QML tree: a vertical bar, the desktop widgets, the
wallpaper, and the popups. Runs under Hyprland, whose side of the desktop —
`hyprland.lua`, the `hyprvtb` plugin, the sandbox — is `../AGENTS.md`. Repo-wide
rules are `~/nix/AGENTS.md`.

**Read `../AGENTS.md` too if your change touches window management, titlebars,
logout, or anything the compositor owns.**

---

## Getting an edit live

Most files here are installed as **Nix-store symlinks**. A rebuild swaps the
symlink, but Quickshell watches the *resolved* store path — so the swap does
**not** trigger its hot reload and the panel keeps running the old tree. Force
one by modifying the single real file it watches, `~/.config/quickshell/
Theme.qml`, **in place (same inode)**:

```bash
sudo rebuild-top
cp ~/.config/quickshell/Theme.qml /tmp/Theme.bak
printf '\n// x\n' >> ~/.config/quickshell/Theme.qml   # append…
cat /tmp/Theme.bak > ~/.config/quickshell/Theme.qml   # …then restore, in place
```

- **Do NOT use `sed -i` or `mv`** — a rename is a new inode, so no reload.
- It **dedupes by content**, so an identical rewrite is a no-op.
- A reload rebuilds only Quickshell's QML tree in-process; it never touches
  Hyprland. A parse error keeps the old tree and fires a toast, so it cannot
  crash the session.
- A **new** `.qml` file must be `git add -N`-ed before the rebuild — the tree is
  dirty and flake eval ignores untracked files, so a brand-new `Foo.qml` is
  silently missing from the build otherwise.

**`Theme.qml` is seed-once.** It is installed only if absent, because
`wal-set.sh` rewrites it in place at runtime. To change it, edit **both** the
nix source here and the live `~/.config/quickshell/Theme.qml` — with a targeted
string edit, never a wholesale overwrite, or you reset the live wal palette.
Check with `~/nix/tools/seed-drift.sh` before you start and after you finish.

---

## A reload must look like a state change IN PLACE, not a re-entry

That is the standing bar for anything on this desktop, because a wallpaper or
theme change rewrites `Theme.qml` and therefore reloads the panel. Quickshell
rebuilds the *whole* QML tree, so without help every widget comes back empty and
visibly refills: the disk widget maps at its one-line "reading…" height and
grows twice as its scripts land (dragging every in-place stackable above it up
the screen), the forecast collapses until curl returns, cava restarts so the VU
and spectrum drop to the floor, and the chart ring buffers restart from zero.

Two mechanisms carry state across, both wired in `shell.qml`:

**The pin set** — mirrored to `$XDG_RUNTIME_DIR/qs-live-pins` and read back
SYNCHRONOUSLY (`FileView { blockLoading: true }`) in `Component.onCompleted`,
then applied with `snapPinned()`. The file's absence doubles as the
login-vs-reload flag (`$XDG_RUNTIME_DIR` is wiped at logout), and the PID written
alongside (`v2 <pid> …`) separates a RELOAD of that process from a fresh
`quickshell` start. That distinction is the whole trick:

- **On a reload Quickshell hands the outgoing window's layer surface to the
  incoming object, still mapped** — so `SlidePopup` must NOT run its layer remap
  there. A remap destroys that surface and opens a new one, which Hyprland fades
  out and in: the widgets blink on every wallpaper or theme change.
- **Everywhere else the remap is mandatory, including pre-map.** Quickshell
  latches the layer when it *creates* the window (at component completion,
  regardless of `visible`), so the login fan would otherwise come up on Overlay
  with every desktop widget floating on top of windows.
- Both halves are checkable without looking: `hyprctl layers` — the `qs-*`
  widget namespaces belong in level 1 (bottom) — and Hyprland's event socket,
  which must emit **no** `closelayer`/`openlayer` for them across a reload.

**The widgets' contents** — a `PersistentProperties` block, which hands
properties from the outgoing tree to the incoming one in-process. Each source
exposes `stateJson()`/`restoreState()` plus a `stateRev` counter that
`shell.qml` snapshots on; the 60fps VU/spectrum feeds are sampled on a 250 ms
timer instead. Restore fires after every `Component.onCompleted` but inside the
same synchronous reload pass, so no frame renders in between. **Two
constraints, both found the hard way and both silent when violated:**

- It must be a **direct child of the root `Scope`**. One level down inside a
  plain `Item` it never restores — a non-Reloadable parent breaks the matching
  chain.
- **Every carried property must be a STRING.** Quickshell alternates between two
  QML engines across reloads and a JSValue (any `property var` holding an array
  or object) cannot move between them, so a `var` arrives `undefined` on every
  *other* reload, with only a `JSValue can't be reassigned to another engine`
  warning to show for it.

```bash
qs ipc call state carried   # sizes of each carried blob + live buffer lengths
```

Poll that repeatedly across a forced reload: all non-zero and `cpuHist` counting
up monotonically means the swap worked; a reset to 0 means something regressed.

---

## Two view modes, and the drag handle IS the switch

`ViewMode.qml`. `classic` is the 48px vertical bar this config has always had,
with the desktop widgets pinned out on the wallpaper. `dock` turns the panel
into a wide column (14–33% of screen, default 15%): `DockHeader.qml` (runner
button at the left, task icons flowing across and wrapping) over `DockGrid.qml`
(the widget grid). There is no toggle button — you grab the bar's inner edge
(`edgeGrip` in `shell.qml`) and pull.

```bash
qs ipc call view toggle|dock|classic|mode
```

- **Opening it has ONE destination.** The entry drag is a gesture, not a resize:
  the bar holds at 48px until the pull passes `enterFrac` (5% of screen) past
  its own width, then opens in one movement at `dockPx` — the same size every
  time. Resizing only happens once you are already in dock, where the panel does
  track the pointer, clamped to `[minFrac, maxFrac]`. **Don't "improve" this
  into a continuous stretch on entry**; it was that once and the user asked for
  the single snap.
- **`exitFrac` (10%) must stay below `minFrac` (14%).** If the collapse
  threshold reached into the legal width range, the narrowest dock the user is
  allowed to pick would already sit inside the "about to collapse" zone, and the
  panel could never rest there.
- **Both layouts are always instantiated**, crossfaded on `ViewMode.showDock`
  (which follows the drag LIVE, so the panel visibly *becomes* the dock as you
  cross the threshold rather than snapping at release). A faded-out layout must
  set `visible: false` — otherwise the classic hover zones keep firing popups
  from under the dock panel.
- **`liveWidth` vs `barWidth`:** `liveWidth` is what the bar renders at this
  frame (pointer-tracking mid-drag); `barWidth` is the committed value, and only
  it feeds the persisted setting and the wallpaper. Read `ViewMode.barWidth`,
  **not** `Theme.barWidth`, for "how much screen does the panel take" —
  `Theme.barWidth` is now only the *classic* width.
- **Dock mode retires the desktop widgets** (they belong to the grid there) and
  restores the exact pre-dock pin set on the way back. `shell.qml`'s
  `Component.onCompleted` returns early in dock mode, so neither the reload
  restore nor the login fan re-pins anything.

### One widget, two places: `*Content.qml` + a data singleton

A widget is drawn by a **content component** and its data belongs to a
**singleton**. Neither half may live in the popup, because the popup is no longer
the only thing that shows it — the same widget is also a tile in the dock grid,
and **both copies exist in the QML tree at once.**

| Layer | Files | Owns |
|---|---|---|
| data | `SysInfo`, `Weather`, `Disks`, `Media`, `Procs` | polling, scripts, carried state |
| view | `CpuContent`, `GpuContent`, `EthContent` (all on `MetricChart` → `ChartCanvas`), `WeatherContent`, `CalendarContent`, `ClockContent`, `DiskContent`, `MediaContent`, `TaskManagerContent` | drawing, and nothing else |
| host | `<Name>Panel.qml` (a `SlidePopup`), `DockTile` in `DockGrid` | where it sits |

Three rules, all of which exist because there are two live copies:

- **`active` is the contract, and it defaults to FALSE.** Every content component
  takes it, and everything that costs something — a Canvas repaint, a `Process`,
  a `Timer` — hangs off it. The popup passes `root.open` (**not** `visible`: a pin
  flips the layer, which unmaps the surface for 32ms, and cava would stop and
  respawn every time); the grid passes `dockLayout.visible`. Get this wrong and
  you get two cavas, two `smartctl` timers, and two different answers from
  `state carried`. It defaults to false because `DockTile` applies it through a
  `Binding` on an asynchronous `Loader`: a `true` default meant every grid tile
  ran one full `/proc` scan and one drive scan at construction, before that
  binding landed, for a widget nobody was looking at.
- **Consumers register with `watch(obj, on)`, which is a SET, not a counter.**
  Re-registering is a no-op, so a re-evaluated binding or a reload restore cannot
  leak a reference and leave the scripts running against nobody.
- **Content components must STRETCH.** A popup gives one its implicit size; a
  grid cell gives it the cell. So: title top, legend bottom, chart taking the
  rest — never a fixed `196x96`, and widths derived from `width`, not literals.
  `implicitWidth` stays a CONSTANT, since the host derives its own width from it
  and a width-dependent `implicitWidth` is a loop.

`MetricChart.qml` is the shared body of cpu/gpu/eth; each is ~10 lines of series
and legend on top of it. Its `series` is a binding over the source ring buffers,
so `onSeriesChanged` is the only repaint trigger any of them needs — don't add
`Connections` back. Note it exposes `axisMax`, not `scale`: `scale` is a
`QQuickItem` property (the transform), and shadowing it breaks rendering.

```bash
qs ipc call live all     # mode + which data singletons are actually polling
```

That is the check for it. A `true` for something not on screen is the bug; two
copies of a widget both live is the bug this whole split exists to prevent.

### The dock grid is ONE PAGE, and must stay one

`DockGrid.qml` is `columns` x `rows` (4 x 26) filling the panel exactly: the row
height is DERIVED from the panel's height, not a fixed pixel value, so every
widget is on screen at once at any panel height. **No scrolling.** A first version
used 44px rows and a `Flickable`, which made the default layout ~1900px tall on a
1080px screen; the user's requirement is that nothing is below the fold.

The consequence is a real constraint: a new widget takes rows away from the
others, and if none can spare them, it doesn't fit. Neither count is derived from
the panel WIDTH — the panel ranges over 14-33% of the screen, and changing the
geometry inside that range would invalidate every saved placement each time the
edge was dragged. Widening the panel widens the columns instead.

`placements` is plain data — `{key, src, col, row, cs, rs}` — loaded by file name
through `DockTile`'s `Loader`. That is deliberate: phase 3 makes that array the
thing the user drags and the thing that gets persisted, and
`cellX/cellY/cellW/cellH` stay the single place grid coordinates become pixels.

Reading bottom-up, the layout is calendar+clock side by side on the bottom row,
weather above them, media above that, and the task manager taking the rest.

The forecast is a GRAPH, not a table: twenty points (09:00 and 21:00 for ten
days, `Weather.slots`) in the height a seven-row table spent on hi/lo pairs.
Night halves are shaded, so the two-per-day structure reads. The daily block
can't drive it — a daily max isn't tied to a time of day — hence the `hourly=`
query.
**The disk widget currently has no dock tile** — it is classic-mode only.

**Dead space is a number, not an opinion:**

```bash
qs ipc call live tiles     # per tile: got, wants, slack
```

Aim for a small POSITIVE slack — but read it knowing `wants` is the widget's
NATURAL height, not a minimum. The widgets absorb slack themselves: the
calendar's week rows, the clock's face, the forecast's day rows and the player's
artwork all grow or shrink into the tile they are handed rather than leaving a
gap under them. A large negative slack on the clock is therefore correct, not a
bug — the bottom row is sized by the CALENDAR, and the clock draws a smaller
face to match. Each of those widgets keeps a `natural*` constant that
`implicitHeight` is built from; deriving it from `height` instead is a binding
loop, since the popup takes its height from `implicitHeight`.

### The task manager

`TaskManagerContent.qml` + the `Procs` singleton + `scripts/proc-list.py`.

- **CPU% is instantaneous**, from two `/proc` samples 0.4s apart — NOT `ps`'s
  `%cpu`, which is the average over a process's whole lifetime and so reports an
  idle daemon as busy forever and a process that just started spinning as idle. A
  task manager whose numbers converge after an hour isn't one. That 0.4s per
  refresh is why `Procs` is `watch`-gated like the others.
- **Don't trust `comm` for the name.** The kernel caps it at 15 characters and on
  NixOS everything runs through a wrapper, so it reads `.quickshell-wra` /
  `.claude-wrapped`. The script prefers `argv[0]`'s basename — except for
  Chromium/QtWebEngine helpers, which rewrite their entire command line into
  `argv[0]`, so a "name" containing spaces or over 24 characters falls back.
- **Kill is SIGTERM on left click, SIGKILL on RIGHT.** The rows re-sort under the
  cursor every 2s; an unrecoverable action must not be one mis-timed left click
  away.
- The charts are a 4x2 block of SQUARE cards — cpu, gpu, mem, net, load, vram,
  swap, fan — sharing `ChartCanvas.qml` with the popups. Square means the card
  height follows the panel WIDTH, so a taller tile turns into more visible
  processes rather than letterboxed charts.
- **The chassis-fan bar hides itself, and on `top` that means it never shows.**
  `/sys/class/hwmon` exposes no `fan*_input` at all here — the only hwmon
  devices are nvme, spd5118, k10temp, amdgpu, mt7921 and the trackball battery,
  because no Super-I/O driver (`nct6775` &c) is loaded for the B650's sensor
  chip. `SysInfo.fanCount` is 0 and the bar is `visible: false`; it lights up on
  its own if that driver is ever loaded. The `fan` CARD is a different sensor —
  the GPU fan, via nvidia-smi, as a percentage — and its 0% at idle is a real
  reading, since the card stops its fans when cool.
- `sysinfo.sh`'s fields are POSITIONAL and `SysInfo.qml` indexes them, so new
  ones go on the END; everything past `batteryCharging` is the task manager's,
  and the parser guards on the field count. The nvidia extras (fan, power, vram)
  ride along in the SAME `nvidia-smi` query — its cost is process startup, not
  the number of columns.
- Memory is `MemAvailable`, not `MemFree`. MemFree alone reads as "almost none"
  on any machine that has been up a while and is simply a wrong thing to show.

### The clock's three faces

`ClockContent.qml` draws `analog`, `dots` (5x7 dot matrix) or `seg` (seven
segment) from one Canvas, cycled by the button in its own top-right corner. The
choice is a persisted setting (`clockFace`), not local state, so it survives the
reload that every wallpaper change causes and both copies of the widget agree.

`dots` is NOT a Canvas: it is a `Repeater` of `PixelText` items drawing the
font's own U+25A0, one per LIT cell, so the dots rasterise like every other
glyph on this desktop. Only lit cells exist — there is no unlit grid. (Checked
against the font's cmap: More Perfect DOS VGA has U+25A0 and U+2588 but not the
bullet or the circle.) It is driven by a MINUTE-precision `SystemClock`; the
seconds clock would rebuild the cell model 60x more often than anything changes.

**For `seg`, the unlit colour is load-bearing and was wrong twice.** `Theme.dim`
against `Theme.accent` is nowhere near enough contrast — every digit reads as an
8 — so unlit segments go all the way down to `Theme.bgAlt`. The dot face had the
same problem before the unlit grid was dropped entirely. Both were settled by
rendering the same glyph data and layout maths out to a PNG and looking at it,
which is how to check a face like this without making the user click through
three modes.

**Check new glyphs against the font's cmap before shipping them.** More Perfect
DOS VGA has `°` `·` `■` `█` but NOT `—` `…` `•` `↑` `−` `♫`. A `PixelText`
containing a missing glyph falls back to another font for it and loses ~5px of
ascent, clipping the whole line — which is why the media widget's empty-title
placeholder is `"-"` and every "reading..." is three dots.

> Adding several new `.qml` files in one rebuild produces a burst of **failed**
> reloads in `qs log` ("`X is not a type`") as home-manager writes them one at a
> time. Harmless — the reload guard keeps the old tree up — but don't read the
> first failure as the change being broken. Check for the final
> `Configuration Loaded`.

### Verify the drag by MEASURING it

```bash
qs ipc call view geom    # widths + thresholds
qs ipc call view trace   # one dragWidth,surfaceWidth,liveWidth sample per pointer event of the last drag
```

This gesture cannot be judged from a log line, and has been mis-diagnosed twice
by reasoning about it instead. Read the trace.

---

## The law: NOTHING that must track the pointer may be a layer-surface SIZE

A layer-surface resize is a configure/ack roundtrip, so any surface whose width
follows the cursor is a frame or more behind it. Everything pinned to the panel
edge is computed from `ViewMode.liveWidth` and lands exactly, so a
surface-sized edge visibly disagrees with all of it for the whole drag. Three
places this bit, all fixed the same way — **put the moving edge in an ITEM
binding inside a surface that does not resize:**

- **The panel** (`shell.qml`). The visible bar is `barBody`, an Item anchored to
  the screen edge with `width: ViewMode.liveWidth`. The surface is a CONSTANT
  `ViewMode.maxPx`, transparent, input-masked to the bar, painting its
  background from a Rectangle inside `barBody`. It must stay constant: sizing it
  to the bar except while dragging put a resize on the press and another on the
  release, and each made the panel visibly JUMP (right on click, left on
  release) — resizing a surface anchored to the right edge moves it too, and the
  compositor can apply the new geometry a frame before the matching buffer
  arrives. Same cause as the old flick-away-and-back when the committed width
  landed.
- **The accent stripes** (`EdgeAccent.qml`). The horizontal ones are FULL-WIDTH
  surfaces (`exclusionMode: Ignore`) that never resize, with the visible stripe
  an inner Rectangle of `parent.width - ViewMode.liveWidth`. Two earlier
  versions were wrong: anchored to both sides and shortened by the exclusive
  zone (which stops updating once the zone is frozen during a drag, so they only
  resized on release — invisible while the panel GREW because the stripe was
  covered, an obvious gap the other way), then with the *window's*
  `implicitWidth` bound to `liveWidth`, which is a surface resize and so lagged
  the cursor.
- **The grip** (`EdgeGrip.qml`) — below.
- **The wallpaper is the deliberate exception**: `WallpaperLayer.qml` tracks the
  COMMITTED `barWidth` and glides to it, because re-cropping a full-screen
  texture per pointer event costs real work for an image nobody is watching
  mid-drag. The panel edge is what the eye follows.

### The resize handle is its OWN full-screen surface

`EdgeGrip.qml`, not an item in the panel — and that is load-bearing. Wayland
delivers pointer coordinates in SURFACE coordinates, so mid-drag the item tree
has already advanced to the requested width while the surface has not: every
event is wrong by whatever the surface still owes. Measured with `view trace`,
the computed width moved 1:1 with the SURFACE width while the pointer was nearly
still. **No arithmetic inside a resizing surface can escape this** — the
reference frame is itself moving. A screen-sized surface that never resizes
makes a pointer x a screen x. Three traps it encodes:

- **`exclusionMode: ExclusionMode.Ignore` is mandatory**, and you must NOT set
  `exclusiveZone` beside it (assigning it selects "Normal" and undoes it). A
  surface anchored to all four edges is otherwise shrunk by everyone else's
  exclusive zones — it came up 1618px wide against the panel's own 302px zone,
  which both misplaces the grab strip and makes the grip resize with the panel,
  reintroducing the very problem it exists to avoid. Check with
  `hyprctl layers`: `qs-edge-grip` must be the monitor's full width.
- The MouseArea fills the whole window and the grab area is carved out with
  `mask: Region {...}`. Putting the MouseArea *at* the moving edge would
  reintroduce the same bug one level down.
- **A `PanelWindow` is NOT a `QQuickItem`** (it is a `WaylandPanelInterface`),
  so `mapToItem(bar, ...)` throws `TypeError: Passing incompatible arguments to
  C++ functions` — and thrown from inside `onPressed`, that means the drag
  silently never starts, with nothing on screen to explain it. **`qmllint` does
  not catch it**; it only shows up in `qs log`. `mapToItem(null, ...)` (map to
  the scene root) is fine and is what `Tooltip`/`StatusPanel`/`TaskMenu` use.
  Inside a panel, prefer plain arithmetic on a child's own `x` plus the panel's
  `width`, both ordinary property reads.

### Never animate, quantize, or re-zone a live drag

- **Never animate a width that is tracking the pointer.** The `Behavior on
  implicitWidth` is gated on `!dragging || ViewMode.snapping`; an animation on
  the tracked resize means the edge permanently chases the cursor from behind,
  which reads as lag. `snapping` marks the discrete jumps (entry, collapse
  preview) that *should* glide.
- **Never quantize the LIVE drag width.** Quantizing to the 8px grid made the
  edge advance in hops instead of following the cursor. The grid only has to
  hold for the COMMITTED width (that is what the wallpaper is composed
  against), so `quantize()` belongs in `commitDrag()`.
- **Never touch `exclusiveZone` during a drag.** Re-writing it per pointer event
  makes Hyprland recompute the reserved area and re-run the layout in the same
  frame the resize is trying to land in. It is frozen at the committed width
  mid-drag and applied once on release.

### Growing the panel pushes floating windows out from under it

`scripts/push-windows.py`, run from `applyReserve()` only when the reserve GREW.
The exclusive zone reflows tiled windows only, and this desktop is almost
entirely floating. It skips `hidden` windows — those are hyprvtb's rolled-up and
minimized ones, parked off-screen deliberately.

- Pixel dispatchers under the Lua config are `hl.dsp.window.move({window=,x=,y=})`
  and `hl.dsp.window.resize({window=,x=,y=})`, both ABSOLUTE, and **resize must
  come before move** — resizing re-anchors the window, undoing a move issued
  first.
- **Push the FRAME, not the client rect.** `at`/`size` from `hyprctl clients`
  exclude the chrome, and `hyprctl` reports decoration extents nowhere. The
  hyprvtb titlebar is VERTICAL on the window's RIGHT edge
  (`DECORATION_EDGE_RIGHT`, `desiredExtents` right = `bar_width * 2` = 64px) —
  the same side the panel is on — so client-rect math leaves exactly the
  titlebar covered, the bug reported on 2026-07-26. Reconstruct the frame from
  `plugin:hyprvtb:{enabled,bar_width}` + `general:border_size` via
  `hyprctl getoption -j` (`enabled` is a global bool, not per-window).

---

## The panel draws the wallpaper — hyprpaper is gone

Removed 2026-07-26. `Wall.qml` (which image + tile/scale), `WallpaperLayer.qml`
(a Background layer surface per monitor), `WallpaperImage.qml` (one cross-fade
frame). Two reasons it had to change: hyprpaper re-rendered its whole background
layer on every set, which reads on screen as the wallpaper FLASHING (`wal-set.sh`
already skipped redundant sets purely to dodge it), and it had no notion of an
OFFSET — so centring the art in the non-panel region meant compositing a fresh
full-screen PNG with ImageMagick for *every* panel width, then setting it, then
flashing. Drawn here, the recentre is a property binding on
`ViewMode.liveWidth`, so it follows the drag at frame rate, and a wallpaper
change is a cross-fade.

- `wal-set.sh` still DECIDES the wallpaper and owns the palette, kitty, cursor
  and OpenRGB work. It now just publishes to `~/.cache/wal/current` (path) and
  `~/.cache/wal/current.mode` (`tile`|`scale`), written **in place** — an inotify
  watch follows the inode, so a temp+rename would silently detach it.
- `--wallpaper-only` is now just those two writes — 14 ms, which is what the
  picker's arrow-key preview rides on. It still must NOT do the full apply: that
  rewrites `Theme.qml`, which reloads the panel.
- **`sourceSize` must never be bound to the item's width** — the width changes
  every frame of a drag and would re-decode a multi-megapixel image per frame.
  It is the monitor resolution for `scale`, and 0 (natural size) for `tile`,
  since a tile scaled to the screen no longer tiles.
- **The blurred backdrop** behind everything is a PRE-COMPUTED file:
  `wal-prepare.sh` caches a 400px-wide real Gaussian per wallpaper
  (`~/.cache/wal/blur-$KEY.png`, path published in `current.blur`) and the panel
  just draws it, so it costs one small static texture and nothing per frame. It
  fills the strip that opens up between the panel edge and the sharp wallpaper
  while the panel is being narrowed (the sharp copy only glides to the new width
  on release). **Keep it static** — it is on screen exactly when the compositor
  is busiest. Two things it encodes: **PNG, not JPEG** (the output is nothing but
  smooth gradients, which is exactly what JPEG bands), and it is a real blur
  rather than the original trick of decoding the wallpaper at ~96px and letting
  the GPU stretch it. That upscale is free but it is *not* a blur — rendered out
  and looked at, the picture was still plainly legible with interpolation facets.
  That path survives only as the fallback for the moment before the cache exists.

```bash
qs ipc call wallpaper status   # path, mode, and whether the visible frame actually DECODED (front=ready)
```

That is the check that made switching hyprpaper off safe rather than a gamble on
a blank desktop.

---

## Verifying

The user does **all** visual, animation and interaction checks — screenshots,
drags, hover, spinner animation, tooltip look. Never screenshot or drive the GUI
yourself unless explicitly asked. Verify by other means:

```bash
qs log | tail            # parse/binding errors — CUMULATIVE across reloads:
                         # snapshot the line count first, then read only the new tail
qs ipc show              # what the panel exposes
qs ipc call <t> <fn>     # view geom|trace, state carried, wallpaper status, …
hyprctl layers           # namespaces, levels and surface sizes
qmllint -I <import paths> Foo.qml
```

- **Never run bare `qs`** — it launches a second panel.
- **Never open a test window on the user's screen** — `~/nix/tools/sandbox.sh`
  puts it on an off-screen virtual monitor. See `../AGENTS.md`.
