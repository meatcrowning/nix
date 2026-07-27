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

### A reload builds the tree from the shipped DEFAULTS — so it must not animate

Carrying the state across is only half of it. The other half is that **every
binding in a fresh tree is first evaluated before `settings.json` has been read
back**, so for the first moments of a reload the whole desktop believes it is in
the shipped default configuration: `viewMode` "classic", `dockWidthFrac` 0.15,
`barWidth` 48. Measured in dock mode at 356px (`console.warn` on
`ViewMode.barWidth`, book):

```
Reloading configuration...
  vm.barWidth -> 48   dock=false        <- shipped defaults
  wp.w        -> 1                      <- surface has no size yet either
  wp.w        -> 1488                   <- classic-width wallpaper
Configuration Loaded
  vm.barWidth -> 230  dock=true         <- default dockWidthFrac
  vm.barWidth -> 356  dock=true         <- the real one, ~25ms later
```

That correction is harmless *as a correction* — it lands inside the load pass,
before a frame. What was not harmless is that the Behaviors were already armed,
so it was played as an ANIMATION: the panel grew out of the screen edge over
200ms, the classic layout crossfaded away behind the dock, and the wallpaper
slid across the screen over 260ms (seventeen intermediate widths in the trace).
The user's report was that the larger panel "fails to hot reload in place" —
correctly, because the desktop was visibly *re-entering* dock mode on every
theme or wallpaper change rather than simply being in it.

**So `ViewMode.settling` is true for the first 400ms of every tree, and
everything that animates a view-mode change gates its `Behavior` on it**: the
bar's width and the two layout crossfades (`shell.qml`), the wallpaper's
`visibleArea` x/width (`WallpaperLayer.qml`), the dock tiles' y/height
(`DockTile.qml`). Anything that changes during the settle SNAPS. It is a
wall-clock window rather than a signal from `SettingsStore`, because the values
arrive from three independent places — the settings file, `Quickshell.screens`,
and the compositor telling the surface its size — and the gate has to outlast
the last of them.

- **Add a `Behavior` on anything that follows a persisted geometry value and you
  must gate it too**, or you have re-added the glitch for that one widget.
- It cannot be fixed by loading the settings earlier. Both alternatives were
  tried and measured: `FileView`'s own `blockLoading` initial load and an
  explicit `reload()` forced from a binding's side effect *both* still leave the
  first evaluation seeing `viewMode: "classic"`, because bindings run before any
  `Component.onCompleted` in the tree and a singleton's completion is at the end
  of the pass. `SettingsStore` does the end-of-pass `reload()` anyway, to bound
  how late the values can be; the gate is what makes it invisible.
- `ViewMode.applyReserve()` is seeded from the settle timer, not from
  `Component.onCompleted`. At completion `dock` is still the default `false`, so
  `_lastReservePx` was seeded 0 — and the next drag release then looked like the
  panel had grown from nothing and pushed every floating window.

```bash
qs ipc call view geom     # ...dragging=false settling=false
```

`settling=true` when nothing is happening means the timer never fired.

**A one-shot handler cannot be gated — it must LOAD. `SettingsStore.loadNow()`.**
Snapping an animation is enough for a binding, which will be re-evaluated when
the truth arrives. A `Component.onCompleted` runs once and is simply wrong. The
reload restore in `shell.qml` opens `if (ViewMode.dock) return;` — and read
`false` on every reload, so in dock mode it re-pinned the saved widget set onto
the wallpaper and had it torn down again ~25ms later when the real mode landed
and `onDockChanged` fired. On Hyprland's event socket that is the
openlayer/closelayer pair per widget this section forbids, on every theme or
wallpaper change.

```qml
function loadNow() { file.reload(); return file.text(); }   // SettingsStore
```

**Both calls, in that order, and the `text()` is the one that does the work.**
`reload()` alone does not deliver — measured three ways (the FileView's own
`blockLoading` initial load, a `reload()` from a binding's side effect, and a
bare `reload()` here) and in all three the next line still read
`viewMode: "classic"`. Reading `text()` forces the blocking read to complete, and
the adapter's properties — and every binding on them — are updated before the
call returns: `dockBefore=false dockAfter=true`. Call it first in any
`Component.onCompleted` that branches on a persisted value.

### `visible` gates layer-surface mapping — never derive it from geometry

A `PanelWindow`'s `visible` is what maps and unmaps its Wayland surface, and an
unmapped window has width 0. So a `visible` computed from the contents' geometry
closes a loop through the compositor, and it does not merely warn: it maps and
unmaps a real surface. `RecordingToast` had `visible: recording || card.x <
card.hidden - 1` over a card whose `hidden` read the window's own `width`, which
Qt reported as a binding loop on every load — and Hyprland logged an
openlayer/closelayer pair for `qs-recording` on every reload, a toast nobody had
asked for being mapped and unmapped behind the scenes. Fixing only the loop was
not enough: the label's implicit width lands a moment after construction, the
slide `Behavior` then animated `x` across the "still on screen" test, and the
surface flickered again.

The idiom, which `SlidePopup` (`_visSurface`) already used and is why it never
had this: **keep an imperative flag**, set it when opening, clear it on a timer a
slide-duration after closing, and let `visible` read the flag.

```bash
# What a clean reload looks like on the event socket:
socat -u UNIX-CONNECT:$XDG_RUNTIME_DIR/hypr/$HIS/.socket2.sock -   # then force a reload
```

No `openlayer`/`closelayer` for any `qs-*` namespace. The one legitimate
exception is `qs-notifications`: `NotificationServer` is `keepOnReload: false`,
so a reload drops the toasts and unmaps it, and `onReloadCompleted`'s own
"config reloaded" toast re-opens it ~300ms later. That pair is the reload
announcing itself, not a surface being remapped.

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

### A task cell shows FOUR window states, and the compositor is the source

`TaskCell.qml` (shared by the classic `Taskbar` and the dock header) colours its
border on a ramp: full `Theme.accent` focused and on screen, a third of the way
to `Theme.dim` unfocused, three quarters of the way rolled up, and `Theme.dim`
minimized — with the icon knocked back in the last two, and the filled
background left to mean FOCUS alone. Roll and minimize outrank focus, because a
rolled-up window can still hold the keyboard.

**Neither state is in the Wayland toplevel list** — they are hyprvtb's, not the
protocol's — so `WinState.qml` polls `hyprctl clients -j` (~4 ms, once a second,
idle when no windows) and derives them from what the plugin actually does:

- **rolled up** = `hidden`, geometry untouched (`vtbDeco` calls `setHidden`).
  `hidden` is also true for a window on a workspace that is not showing, so it
  only counts when the window's workspace is active on some monitor.
- **minimized** = NOT hidden and parked at or past its monitor's right edge
  (`minimizeWindow` moves it to `m_position.x + m_size.x`, in LOGICAL pixels —
  `hyprctl` reports monitor size in device pixels, hence the divide by `scale`).

Both signatures were measured on a live window, not inferred. The join back to
the toplevel list is class + title, which is all this build offers (no Hyprland
window-mapping protocol); two windows of one app sharing a title are the one
case that cannot be told apart.

### Anything the user changes by USING a widget goes in `SettingsStore`

Not a local property, and not a `PersistentProperties` slot. `PersistentProperties`
only survives a reload; `SettingsStore` writes
`~/.config/quickshell/settings.json`, which survives a **logout** too — and a
setting the user chose must not quietly revert at either boundary.

That covers the clicked column heading in the task manager (`procSort`), the
clock's face (`clockFace`), repeat on a player with no `LoopStatus` of its own
(`mediaLocalLoop`), the view mode and the dock's width. The pattern is a
`readonly` property bound to the store plus a setter that writes it, so there is
exactly one copy of the state and no binding to break:

```qml
readonly property string sortKey: SettingsStore.d.procSort
function setSort(k) { SettingsStore.d.procSort = k; SettingsStore.save(); }
```

**The `SettingsStore.save()` is not decoration — without it the change is
reverted within the second.** The reader instance re-reads `settings.json` every
~350 ms (see the polling Timer in `SettingsStore.qml`), so an assignment that
never reaches disk is undone by the next reload, and nothing survives a logout
either. Three settings shipped without it and quietly forgot what the user
chose: the clock's face, the sort column, and the local repeat toggle.

Transient state — a hover index, a list's scroll position — stays local. The
test is whether the user would notice it reverting.

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
- **A per-monitor widget must not own a process.** The VU meter's cava lives in
  `SysInfo`, not in `VuMeter.qml`: that item is instantiated once per MONITOR
  (`StatusPanel` sits inside a `Variants`), so a `Process` in it is one cava per
  screen — two of the three running on this machine were the same meter, the
  second belonging to a leftover sandbox monitor. The levels were already in the
  singleton for reload continuity; the reader belongs there with them. Check with
  `pgrep -a cava`: exactly two, ever — the VU and the media spectrum — however
  many monitors are attached.
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

### Tooltips are driven by `show`, not `visible`

`Tooltip.qml` owns its own visibility: it waits `delayMs` (350) before appearing
and slides out over 220ms — a clipped chip growing leftward from a FIXED right
edge, the same reveal surfer draws for page tooltips and hyprvtb for titlebar
ones. So callers set **`show`** (the hover state) and never touch `visible`;
assigning `visible` from a call site overrides the animation's own binding and
the tooltip is back to blinking in and out.

The window is FULL SIZE throughout and the clip inside it grows. Animating the
popup's own width instead would be a surface resize per frame — a configure
roundtrip behind every step of the animation it is supposed to be.

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

`placements` is plain data — `{key, src, col, row, cs, rs, qRow, qSpan}` — loaded
by file name through `DockTile`'s `Loader`. That is deliberate: phase 3 makes
that array the thing the user drags and the thing that gets persisted, and
`cellX/cellY/cellW/cellH` stay the single place grid coordinates become pixels.

**It is the Repeater's MODEL, so it must not depend on anything that changes at
runtime.** A JS-array model is replaced wholesale when its expression
re-evaluates, and the Repeater answers that by destroying and re-creating every
delegate — with `DockTile`'s `Loader` being asynchronous, every widget comes back
as an empty framed rectangle for a frame or more. That is what "the other widgets
all flash black" meant when the queue drawer's row count was inlined here; five
destroys and five creates per toggle, in a `Component.onDestruction` warn. A tile
that has to move with some state gets a per-tile DELTA (`qRow` rows down, `qSpan`
rows gained, each times `DockGrid.q`) applied in the delegate's own `y`/`height`
bindings, where it is an ordinary property change that the tile's Behaviors
glide.

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

**A MEASURING INSTRUMENT HAS TO BE HARDER TO POISON THAN THE THING IT
MEASURES**, and this one was not. It was plain last-writer-wins into a
singleton, and a whole session was spent reasoning from numbers belonging to a
panel that no longer existed — `tasks got=257` from a tree whose panel was 583px
tall, printed next to `media got=148` while the live tiles were 397 and 241 and
reporting alongside. Two causes, both measured with a per-tile id in the log:

- **A reload overlaps two live panel trees.** Quickshell hands the outgoing
  window's layer surface to the incoming object and the old tree keeps ticking —
  timers and all — for a while after. Both own a full set of `DockTile`s
  reporting under the SAME keys, and the dying one could win the last write and
  keep it forever, because a tile whose height never changes again never
  corrects it. **That overlap is BY DESIGN** — it is what stops every widget
  blinking on a theme change — so the tree is not the thing to fix.
- **Construction and teardown lay a tile out at a degenerate size** (`h=-87
  want=-1` inside a parent -185px tall). Nothing true can be said about a tile
  that is not on screen.

So `DockGrid` takes a GENERATION from `ViewMode.nextGen()` at completion and
stamps every report; older generations are dropped, a newer one wipes the table
first, and non-positive geometry is refused outright. The instrument shows one
panel — the newest — or nothing, never a mixture of two. `DockTile` re-reports
on `onGenChanged` because the delegates complete BEFORE the grid does, so the
first reports go out stamped 0. The regression test is a burst of three forced
reloads followed immediately by `live tiles`: every number must match the panel
you are looking at.

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
- **On book, gpu/vram/fan are replaced by psi, io and batt** (`root.noGpu`,
  keyed on the `Host` singleton). That machine cannot produce the first three at
  all: Asahi's DRM driver exposes no fdinfo engine counters and no devfreq node,
  so there is no GPU utilization anywhere in sysfs; GPU memory *is* system
  memory; and the machine is fanless. What it gets instead is `/proc/pressure`
  ("some avg10" for cpu/io/memory — how much time the machine is costing you,
  which utilization does not say), physical-disk throughput from
  `/proc/diskstats` (parents only, or partitions double-count), and the
  **battery**. All those fields are collected on BOTH hosts — they are sysfs
  reads — and the host only picks which cards to draw. Keyed on `Host`, not on
  the readings being -1, so the grid can't relabel itself two seconds after it
  opens.
- **The `batt` card is book's only per-host reading, and it is a SLOPE.** It
  held whole-machine watts first (`macsmc_hwmon`'s "Total System Power", which
  tracks `macsmc-battery/power_now` one sample behind — 4.7W idle, 18.7W
  loaded); that reading survives as the card's *secondary*, next to the state
  in words — `chg`, `ac`, `full`, and nothing at all while discharging, from
  `SysInfo.batteryLabel`. The graph is charge percent, because "how hard is
  the box working" was already the cpu, psi and io cards' answer three times
  over and "how long have I got" was nobody's. Four things it encodes:
  - **Charging is said TWICE, on purpose.** The sub line is what `MetricCard`
    drops when three readings won't fit the card, and a panel dragged narrow is
    exactly when you still want to know you are plugged in — so the percentage
    itself is prefixed `+` while charging, on the line that is never dropped,
    and the readout goes `Theme.info` with it. Charging also outranks the
    level in the colour ramp: 15% and climbing is not a warning.
  - **Fixed 0-100 axis.** The one card here that must not autoscale — a
    battery resting at 96% would otherwise be drawn against a 96% ceiling and
    read as full-to-empty.
  - **`SysInfo.batteryHist` is SUB-SAMPLED**, one point per `battStepSec`
    (40s) off the wall clock, so the same `chartLen` 90 points span an HOUR
    instead of the poll's three minutes — a battery does not move in three
    minutes and the card drew a flat line. It is the only history here that is
    not pushed every poll.
  - **The battery node is DISCOVERED, never hardcoded** (`sysinfo.sh`):
    `BAT*/` then `macsmc-battery/`, and only if neither exists a scan for a
    `type=Battery` whose `scope` is explicitly **`System`**. "System" rather
    than "not Device" is what keeps `top` unchanged — a HID++ peripheral
    publishes a `type=Battery` node too (that is how the trackball once became
    the desktop's "laptop battery"), and anything that declines to say what it
    belongs to is not claimed. `batStatus` (last field, a code — 0 none,
    1 discharging, 2 charging, 3 full, 4 not charging, 5 unknown) exists so
    "on AC" and "discharging" are distinguishable; the same wattage means
    opposite things in each.
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
- Every card carries a `tip`, shown on hover through the shared `Tooltip`. The
  labels are four characters of jargon each and the card has no room to explain
  itself; the tooltip is where "psi" or "res" gets to say what it measures.
- **The filter box is the only thing on this desktop that takes the keyboard**,
  and it gives it back. `shell.qml` sets `WlrLayershell.keyboardFocus: OnDemand`
  on the bar while `Procs.filterHover || Procs.filterFocus || Procs.filterLatch`
  (and dock mode), and `None` otherwise. Three halves, all load-bearing:
  - **HOVER is what arms it.** Hyprland grants an on-demand layer surface the
    keyboard on the next pointer MOTION over it — measured in a nested
    compositor, not on a click (`processMouseDownNormal` only calls `refocus()`
    when the press lands on a *window*). So the surface has to already be
    focusable before the pointer gets to the box.
  - **`filterLatch` is what makes giving it back safe, and it is the fix for
    "focus is stolen and no window ends up focused".** Dropping the surface from
    on-demand to none *while it holds the keyboard and the pointer is still over
    the panel* leaves the compositor focused on **nothing**:
    `CLayerSurface::commit` calls `refocusLastWindow`, which looks for a window
    under the pointer, finds this panel, and gives up — and with
    `input:follow_mouse = 2` nothing later restores it, so the keyboard is dead
    until the user clicks. The transition posts Hyprland's `activewindow>>,`;
    both the window and the panel then report no keyboard. That is exactly what
    the documented "click somewhere else in the dock to blur the box" gesture
    did. So the latch holds the surface focusable from the hover until the
    pointer leaves the **bar** (a passive `HoverHandler` on `barBody` clears it),
    and the hand-back happens with the pointer over a window — the case the
    compositor gets right. Repro harness: a nested Hyprland plus a probe layer
    surface, driven by `hl.dsp.cursor.move` and read back through each surface's
    own `activeFocus`. `hyprctl activewindow` is **not** an instrument here: it
    reports `CFocusState::window()`, which `rawSurfaceFocus` never clears, so it
    keeps naming a window that has not had the keyboard for minutes.
  - **OnDemand, not Exclusive.** Exclusive keeps sending us the keyboard after
    the user clicks into a window, so their next keystroke goes to the filter box
    instead of what they just clicked on. OnDemand hands it back as part of that
    click. A click that stays INSIDE the panel never reaches the compositor's
    focus logic, so a catcher in `dockLayout` calls `Procs.blurFilter()` and
    declines the press (`mouse.accepted = false`) so the widget underneath still
    gets it.

  The widget clears both flags when it goes inactive or is destroyed: a stale
  `filterFocus` would leave the panel holding the keyboard with nothing on screen
  to type into. The filter text is deliberately NOT in `SettingsStore` (it is a
  question you are asking now, not a preference) but IS carried across a reload
  in `Procs.stateJson`.

### The player's queue drawer, and where its rows come from

The queue is **served by the player app**, not scraped: MPRIS carries the current
track and nothing else (its TrackList interface is optional, and Quickshell
implements no client for it). `apps/player/main.py`'s `start_queue_server`
listens on `$XDG_RUNTIME_DIR/player-queue.sock` and speaks one line at a time —
`{"index": n, "tracks": [...]}` pushed on connect and on every queue/index
change, `GOTO <index>` back. `Media.qml` holds the socket; `MediaContent.qml`
draws it.

- **Push, not poll.** The drawer is on screen behind a slide animation; a file
  re-read on a timer would be both later and more work.
- **Only connect while the player has a WINDOW open** (`Media.playerUp`, from
  the toplevel list). Quickshell logs a warning on every failed connect and
  `qs log` is cumulative, so a blind retry timer fills it with
  `ServerNotFoundError` all day on a machine where nobody is playing music. The
  window list — not "is there an MPRIS player" — because book's player may have
  no `mpris_server` at all.
- **The parsed queue is derived from the raw LINE**, and it is the line that is
  carried across a reload: only strings survive the engine swap.
- **The drawer's rows come off the FORECAST**, not the task table:
  `DockGrid.queueRows` (4) moves them between the two tiles and
  `SettingsStore.d.mediaQueueOpen` is the switch, which is why that flag lives in
  the store rather than inside the widget. The forecast has a real condensed form
  (`WeatherContent.condensed` — current conditions on one line over a MINIATURE
  of the graph, with the legend, the day names, the axis temperatures and the
  per-sample markers dropped); a shorter process table would just be a shorter
  list, and a clipped graph reads as broken rather than compact.
  **`condensed`'s threshold is derived from the same constants the layout is
  built from** (`chromeH` + `minGraph`), never a literal. The literal it
  replaced forgot the day-label row and three margins, so it was 24px short —
  and everything in that band claimed it could draw a forecast and then handed
  the Canvas 0-18px, two axis temperatures on top of each other with the day
  names under the legend. That is the "the weather widget displays nothing"
  state: not an empty widget, an expanded one with no room to be expanded in.
  The header is positioned by a clamped `y`, not by anchors switched on
  `condensed` — alternating `top` and `verticalCenter` through `undefined`
  leaves both briefly set, which Qt resolves by ignoring one of them.
  **Condensing is not the same as dropping the graph** — there are THREE tiers,
  and each one is a derived threshold rather than a literal. Full (`chromeH` +
  `minGraph`, 40px). Condensed-with-miniature (`miniChromeH` + `minMiniGraph`,
  24px): the same twenty points and night bands drawn thinner, because at that
  size it is the labels and markers that stop being readable, not the line, and
  the line is what the forecast is for. Bare header only, below that — the graph
  is dropped ENTIRELY rather than drawn illegibly, since a canvas handed less
  than `minMiniGraph` is the same overlapping-temperatures sliver the derived
  threshold exists to prevent, and it must not come back in through the
  condensed door.
  `queueRows` is a MAXIMUM, capped so the forecast keeps at least
  `minWeatherRows` — the row height is derived from the panel height, so on a
  short panel (or under a tall dock header) two rows can be shorter than the
  form the widget is being asked to draw, and a widget squeezed below its own
  minimum draws nothing at all. `DockGrid.minWeatherPx` mirrors
  `WeatherContent.minCondensed` and therefore INCLUDES the miniature graph:
  asking for that form is asking for the room it needs, and on this panel it is
  what takes the drawer from four rows to three. The cap is legal only because
  `q` is not in `placements`.
- **The drawer takes the rows the grid ADDED** — `height - naturalRest -
  restSlack`, with NO floor and NO animation of its own — so the artwork row,
  which is the leftover, is the same size at every frame of the slide AND at
  both ends of it. `restSlack` is the slack the tile already had while the
  drawer was in (`qs ipc call live tiles` reports it), and it is the difference
  between the two: without it the drawer took that slack too, so the cover
  measured 65x65 closed and 60x60 open — and since `artBox.width` follows
  `mid.height`, the cover changed in both dimensions and the spectrum's left
  edge moved with it. The whole top of the widget reflowed around a queue that
  opens underneath it. It is SAMPLED, not derived, and the sample is guarded on
  `!drawerOut && !Media.queueOpen`: on a reload with the drawer already out the
  tile is laid out at its open height before this component has decided the
  drawer is out, and a sample taken on `!drawerOut` alone recorded 98px instead
  of 5 and computed a zero-height drawer for the rest of the session.
  `implicitHeight` adds a CONSTANT for the open state; deriving it from the
  drawer's own height, which is derived from the item's height, is a binding
  loop. **Both of the drawer's own animations were bugs**, and both showed up as
  the cover art ballooning before the queue arrived:
  - A `Behavior on height` here is an animation chasing a target that is ITSELF
    animating (the tile's glide), so it retargets every frame and permanently
    trails. Measured: the tile went 217→270px while the drawer was still at
    25px and the artwork absorbed all of it — 111, 126, 139, 148, 154, 159,
    162, 164 — then snapped back to 60.
  - On the close the flag flips in one frame while the tile takes 200ms to shed
    its rows, so the drawer tracks `drawerOut`, which is `Media.queueOpen` held
    true for one animation on the way down. `drawerOut` must be a plain property
    seeded in `Component.onCompleted`, not `property bool drawerOut:
    Media.queueOpen` — an untouched binding wins the first close outright.
    Gating a `Behavior` on `enabled: !Media.queueOpen` does NOT work: both
    bindings hang off the same flag and the height was written before `enabled`
    had been re-evaluated (measured — the popup copy animated and the tile did
    not).
- `DockTile` glides `y` and `height` so the two tiles trade rows visibly. **Only
  those two** — `x`/`width` follow the panel edge during a resize drag, and
  animating anything that tracks the pointer is the law this panel does not
  break.

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

**Both digital faces blink their colon on `seconds % 2`, in `Theme.bgAlt` when
unlit** — one beat, one unlit colour, so cycling between `dots` and `seg`
doesn't change the rhythm. On `dots` the colon is NOT in `dotCells`: that array
is a Repeater model, and a model replaced once a second destroys and re-creates
all ~64 digit delegates every tick. Its column is published separately as
`colonCol` (walked the same way `dotCells` walks the string) and its two dots
are their own fixed `model: 2` Repeater, so a tick recolours exactly two items —
no model rebuild, no relayout, no Canvas repaint. The seconds `SystemClock` is
`enabled: root.active`, and its `onDateChanged` skips the Canvas entirely in
`dots` mode, so an off-screen copy of the widget costs nothing per second.

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

**That rule covers hardcoded UI strings. Text that comes from OUTSIDE — track
tags, window titles, filenames — cannot be written to suit the font, so it has
to be mapped on the way in.** `Media.px()` does that for the player: the
typographic punctuation the font lacks (`’ ‘ “ ” – — ‐ … − • ′ ″ ⁄ ﬁ ﬂ`, plus
the exotic spaces) onto ASCII equivalents, applied to `dispTitle`/`dispArtist`
and to the queue rows where they are parsed. It is **display only** — the tags
on disk and the queue index sent back down the socket never go through it — and
it is deliberately a lookup table, not "strip anything the font lacks": 427 of
the 11k tracks in the library carry U+2019 and 140 carry U+2010, but ~830 have
CJK or fullwidth titles with no ASCII form at all, and a title turned into
question marks is worse than one drawn in the wrong font. Those still sit low;
fixing them needs a pixel font with CJK coverage. Anything else on this panel
that renders library or window metadata wants the same treatment.

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

## The bar dims itself for the sudo modal (`Askpass.qml`)

Hyprland's `dim_around` — the `askpass-dim` window rule that gives the `sudo -A`
password dialog its Vista-UAC treatment — is drawn in the **window** pass. The
bar is a layer-shell surface on the `top` layer, which renders *above* that, so
the desktop went dark and the panel stayed bright. `Askpass.qml` is the switch
and `shell.qml` paints a matching scrim over `barBody` at
`decoration:dim_strength` (0.5) — change one and change the other.

Detection is **self-observed**, off the `ToplevelManager` list the taskbar
already runs on, matching `appId === "vista-askpass"`. There is deliberately no
IPC call from the dialog into the panel: `sudo -A` is load-bearing here, and a
dead or wedged panel must never be able to break it. The worst this design can
do is leave the bar undimmed. Full seam: `apps/askpass/AGENTS.md`.

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

## Scrolling: use the `Kinetic*` types, never a bare `Flickable`

**Every new scroll area in this directory MUST be a `KineticListView`,
`KineticGridView` or `KineticFlickable`** — never a bare `ListView`, `GridView`,
`Flickable` or `ScrollView`. They are the base type with three lines bound to
the `Kinetic` singleton and nothing else, so `model`, `delegate`, `header`,
`section` and the attached `ListView.*`/`GridView.*` properties all behave
exactly as before; the only thing you give up is the chance to be inconsistent.

**`Kinetic.qml` is the single source of truth** for the panel's scroll physics.
Change a number there and every scroll area changes with it; do not write a
deceleration literal into a widget. Set `flickDeceleration` per instance only if
that surface genuinely needs to differ, and say why in a comment.

**Wheel handlers on DISCRETE controls (volume, brightness, tray `Scroll()`) MUST
go through `WheelNotch`**, never a sign test. Declare one inside the MouseArea
and act on `notch.steps(wheel)`.

### Why the panel needs its own deceleration at all

Momentum on this desktop is synthesized by the **compositor** — hyprvtb's
`vtbKinetic` (≥2.78), `../AGENTS.md` and `docs/kinetic-scroll.md` — so it
normally reaches every toolkit as ordinary high-resolution axis events and no
client has to implement anything. **But hyprvtb refuses to coast over a layer
surface, wholesale and deliberately** (`vtbKinetic.cpp`, the `layer-focus` start
gate): the bar's brightness/volume steppers act per event, so a one-second coast
would be forty `wpctl` spawns. Almost all of this panel *is* layer surfaces —
the bar, every `SlidePopup`, `Launcher`, `WallpaperPicker`, `Cheatsheet`. Only
`Settings.qml` and `FileBrowser.qml` are Quickshell `FloatingWindow`s, i.e. real
toplevels, and only those two get compositor momentum today.

So the panel supplies its own, and the job of `Kinetic.qml` is to make it feel
like the rest of the desktop. The two models do not have the same shape and the
arithmetic that reconciles them is written out in that file: the compositor
decays exponentially (`v0·e^(−friction·t)`, coast `v0/friction`), Qt decelerates
linearly (`flickDeceleration` px/s², coast `v0²/2a`), so they can only agree at
one velocity — anchored at a brisk 1200 px/s flick, `a = v0·friction/2 = 2160`.
Qt's default 1500 is the same as anchoring at 833 px/s, i.e. overshooting every
flick brisker than a slow drag.

**`Kinetic.friction` mirrors `plugin:hyprvtb:kinetic_friction` in
`../hypr-files/hyprland.lua`.** If that key is retuned, this one moves with it —
they are two files, so it is a hand-copy, and that is the one duplication the
design could not remove.

**The vendored apps have the same convention under a different roof**
(`apps/qmlcommon/`, `apps/AGENTS.md`): same rule, same friction, same reasoning.
The two trees cannot share a component — the panel's QML is Quickshell's and the
apps' is plain Qt — so they are deliberate parallel implementations. Retune one
and retune the other, or the desktop stops feeling like one thing.

### Sign tests are the defect class

`if (wheel.angleDelta.y > 0) stepUp()` treats every event as one full step. A
touchpad is a ~125 Hz stream of events whose individual deltas are a fraction of
a pixel (measured in the player: 226 of 413 events in one gesture carried
`pixelDelta == 0`), so a two-finger nudge over the bar's `vol` fired dozens of
5 % steps and spawned a `wpctl` per event. `WheelNotch` accumulates instead:
both branches of a Qt wheel event reduce to the same unit — a real wheel click
is `angleDelta` 120 with `pixelDelta` 0, and QtWayland sets `angleDelta = 12 ×`
the surface-pixel delta — so it banks `pixelDelta*12` (or `angleDelta` when
there is no pixel delta) and emits one step per `Kinetic.detent`. One physical
wheel click stays exactly one step; 10 px of finger travel is also one step; the
sub-notch remainder is carried, and a burst is clamped to `maxSteps`.

Keeping these controls notch-based is the *right* answer, not a compromise: they
are steppers, not scroll surfaces, and a coast that walks brightness to 0 is a
bug. Notching them is also what would make hyprvtb's blanket layer-surface
exemption narrowable later — the panel is no longer the reason it exists.

### The reload caveat

Compositor momentum is on here because of the **`kinetic` config key in
`hyprland.lua`** (per host via `hypr-host.nix` → `host.lua`: on for `air`/`book`,
off on `top`), which survives reloads and relogins. A runtime
`hyprctl eval "hl.plugin.hyprvtb.kinetic_set(true)"` does **not** — `hyprctl
reload` clears it, and so does every plugin hot-swap. Never make anything here
depend on the runtime override being set. Nothing in this directory does: the
`Kinetic*` types are Qt-side and work whether the compositor is coasting or not.

```bash
grep -n "kinetic" ~/nix/home/prog/hypr-files/hyprland.lua   # BOTH copies: seed-once
```

---

## On book the panel can only exec what FEDORA ships

`qs -d` is started by Hyprland, and on book Hyprland is started by the **Fedora**
session — so the panel's PATH is `/usr/local/sbin:…:/bin` and nothing else. No
nix profile. (`tr '\0' '\n' < /proc/$(pgrep -x qs)/environ | grep ^PATH`; even
`/usr/bin/qs` is the rpm quickshell there.) On `top` everything is nix, so the
difference is invisible until a feature simply stops existing on one machine.

**`execDetached` has no stdout and no exit code**, so a missing binary is a
perfect silent no-op. That is exactly what happened to `hyprsunset` — a nix-only
package with no Fedora rpm — and with it night light *and* negative brightness,
for their whole life on book: `sh: exec: hyprsunset: not found`, while
`SettingsApply` set `_sunsetUp = true` on the next line. Nothing else in the
chain was wrong (hyprsunset 0.4.0 binds `hyprland-ctm-control-v1` v2 against the
rpm 0.55.4 compositor, and Fedora's own `hyprctl hyprsunset gamma|temperature`
drives its socket fine — the dim is a CTM the compositor applies in its own
render pass, so Asahi's lack of a DRM gamma LUT never enters into it).

**`NixPath.qml` is the one definition of the fix. Route launches through it
rather than writing the snippet again** — it existed as two hand-rolled copies
(both cava spawns) before it was a singleton, and the user had separately
symlinked `/usr/local/sbin/cava` into the nix profile by hand, which is three
workarounds for one problem:

```qml
NixPath.run(["filer", dir])                       // instead of Quickshell.execDetached
command: ["sh", "-c", NixPath.sh + "exec cava …"] // instead of a bare sh body
```

`NixPath.sh` **appends** — the distro binary keeps winning wherever there is one
— so it is unconditional rather than branched on `host`, and a no-op on top.
Do not hardcode `~/.nix-profile/bin`: that is book's user profile, but on `top`
home-manager is a NixOS module and the path does not exist at all (it is
`/etc/profiles/per-user/lam/bin`, and `/run/current-system/sw/bin` beside it).

`NixPath.launchTargets` is probed once at startup and warns into `qs log` for
anything unresolvable. **Add your binary to that list when you add a launch
site** — silence, not breakage, is what let this rot unnoticed for so long.

```bash
# the audit, from this directory — every launch site, against the bare PATH:
BARE=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
grep -rhno 'execDetached(\[\s*"[^"]*"\|command: \[\s*"[^"]*"' *.qml \
  | sed 's/.*"\(.*\)"/\1/' | sort -u \
  | while read b; do PATH=$BARE command -v "$b" >/dev/null || echo "MISSING: $b"; done
```

Everything else the panel launches is distro-supplied on both machines and was
checked empirically: `sh pkill pgrep kill hyprctl qs wpctl pactl notify-send
grim wl-copy xdg-open kitty brightnessctl ddcutil curl jq python3 hostname
pw-play pw-dump` and the coreutils. The scripts under `scripts/` are `/bin/sh`
and `/usr/bin/env python3` and call nothing nix-only.

**One find here was NOT a PATH bug and needed a nix fix instead**: `wf-recorder`
(Screenshot.qml's record mode) resolved on *neither* path on book, because
`home/pkgs/desktop/wm.nix` skipped it for `air` under "already native on air" —
true of kitty/hypridle/wl-clipboard/brightnessctl, false of wf-recorder, which
Fedora Asahi does not package. Screen recording had simply never worked there.
It is now in the common list. If `NixPath` warns about a target, check whether
the binary is *installed* before assuming PATH.

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
