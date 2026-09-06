# AGENTS.md — the Quickshell panel

The desktop shell's QML tree: a vertical bar, the desktop widgets, the
wallpaper, and the popups. Runs under Hyprland, whose side of the desktop —
`hyprland.lua`, the `hyprvtb` plugin, the sandbox — is `../AGENTS.md`. Repo-wide
rules are `~/nix/AGENTS.md`.

**Read `../AGENTS.md` too if your change touches window management, titlebars,
logout, or anything the compositor owns.**

**Read `~/nix/docs/DESIGN.md` before you draw anything.** It is the desktop's design
language — type, palette, spacing, motion timing, menus, tooltips, rows,
affordance honesty — and it is shared with the compositor plugin and the six
apps so that all four trees come out looking like one desktop. This file owns
the panel's *mechanics*; that one owns the *look*, for every surface at once.

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

**`Theme.qml` is mutable, and RECONCILED on every switch.** It cannot be a
store symlink, because `wal-set.sh` splices the live palette into its
`// >>> wal palette` block in place. It used to be seeded once and then left
alone — which meant a rebuild could never update it, so a pull that changed it
did nothing until someone hand-edited the live copy too. Since 2026-08-05
`tools/seed-reconcile.sh` runs from activation: **edit the nix source here
only**, and the switch rewrites the live file in place, carrying the live
palette block across. A live-only edit is overwritten (copy in
`~/.cache/seed-reconcile/`). `~/nix/tools/seed-drift.sh` is the tripwire and
should stay silent.

---

## A reload must look like a state change IN PLACE, not a re-entry

Theme or wallpaper changes rebuild the whole QML tree. The visible result must
be an in-place state change: widgets keep their pins, data buffers, and layout
without a refill animation or an empty first frame.

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

### A reload starts from defaults — so it must not animate

Bindings in a fresh tree initially see shipped defaults before `settings.json`
is loaded. The correction happens during the load pass; Behaviors must be
disabled until persisted geometry has settled.

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
- Loading settings earlier cannot change QML binding order: bindings run before
  Component.onCompleted, and singleton completion is at the end of the pass.
  `SettingsStore` still reloads there to bound lateness; settling makes it
  invisible.
- `ViewMode.applyReserve()` is seeded from the settle timer, not from
  `Component.onCompleted`. At completion `dock` is still the default `false`, so
  `_lastReservePx` was seeded 0 — and the next drag release then looked like the
  panel had grown from nothing and pushed every floating window.

```bash
qs ipc call view geom     # ...dragging=false settling=false
```

`settling=true` when nothing is happening means the timer never fired.

**A one-shot handler must load, not merely gate.**
`SettingsStore.loadNow()` reads synchronously before handlers branch on a
persisted value; the reload restore in `shell.qml` therefore sees real dock
mode and does not repin widgets onto the wallpaper.

```qml
function loadNow() { file.reload(); return file.text(); }   // SettingsStore
```

**Call both in that order; `text()` forces the blocking read.**
`reload()` alone does not deliver the adapter values before return. Use this
pattern first in any `Component.onCompleted` that branches on persisted state.

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

### A popup that maps at ZERO SIZE kills the whole panel

`xdg_positioner.set_size` rejects a non-positive width or height with a Wayland
**protocol error**, and a protocol error disconnects the client. So a
`PopupWindow` whose `implicitWidth` or `implicitHeight` resolves to 0 does not
draw wrong — quickshell **exits**, and the bar, the wallpaper and every popup go
with it, on the first click that opens it.

**There is almost nothing to find afterwards**, which is why this is written
down rather than left to be re-derived. `SIGKILL`-class death, so no coredump;
`qs log` simply stops mid-sentence with no QML exception; the only record
anywhere is Hyprland's `error in client communication (pid N)` in the journal
(`journalctl -t xsession`), where N is the dead instance — cross-check it
against `$XDG_RUNTIME_DIR/quickshell/by-pid/`. It reads exactly like "some agent
killed the panel".

`ProcMenu.qml` shipped like this on 2026-07-27 and took the desktop down on the
user's first right-click:

```qml
Rectangle { id: box
    anchors.fill: parent                    // = the popup
    implicitWidth: col.implicitWidth        // <- the popup's size…
    Column { id: col
        anchors.fill: parent
        component MenuRow: Rectangle { width: box.width }   // …from its own size
    }
}
```

A `Column` that `anchors.fill`s its parent takes its implicit size from its
children's **laid-out widths**, so the popup's width was defined in terms of
itself: it resolved to 0 and stayed there. Two rules, both in that file:

- **Compute a popup's implicit size only from things that do not follow the
  popup's size.** `TaskMenu.qml` and `Tooltip.qml` do it with explicit
  `Math.max(a.implicitWidth, b.implicitWidth)` over named children; `ProcMenu`
  has a variable entry list, so it MEASURES in `openFor()` (walking the entries'
  `implicitWidth`/`implicitHeight`) and refuses to open on a degenerate result.
  `implicitWidth: Math.max(1, …)` is the floor under both.
- **Measure on your own flag, never on `visible`.** `Item.visible` is EFFECTIVE
  visibility and is false for everything inside an unmapped window — and a popup
  is unmapped whenever it is closed. Measuring over `visible` gives a correct
  size on the first open and 0x0 on every one after it, i.e. the menu works once
  per panel lifetime and then silently refuses forever. `ProcMenu`'s entries
  carry `property bool shown` and let `visible` follow it.

Verify off-screen, never on the live panel: put the popup in a `FloatingWindow`
in a throwaway config, `tools/sandbox.sh exec` it, and open the popup from a
`Timer`. A zero-size one prints `error 0: Invalid size` then
`The Wayland connection experienced a fatal error: Protocol error` and exits
255; a good one prints its size and lives. Cycle close→open at least twice —
that second open is the case above.

---

## One slide, one duration

**Everything on this desktop that slides, grows or glides between two resting
positions runs for `ViewMode.slideMs` (260 ms) on `ViewMode.slideEasing`
(`Easing.OutCubic`). Take those two properties; never write a duration literal
into a widget.** That includes anything you add: a new drawer, popup, tile,
reveal or panel. It is a design-language rule, not a per-widget choice — the
repo-wide statement of it is `~/nix/docs/DESIGN.md`.

**The numbers are hyprvtb's window roll**, because that is the largest and
most-used motion here and the one the user judges everything else against:
`../hyprvtb/vtbDeco.cpp`, `VTB_ROLL_DURATION = 0.26f`, `VTB_ROLL_SLIDE_FRAC =
0.55f`, `rollEaseOutCubic` / `rollEaseInOut`. The roll is two beats inside those
260 ms — the drawer slide over the first 55 % (ease-out cubic), the set-down over
the remaining 45 % (ease-in-out cubic), reversed for roll-out — so:

- **`slideMs` matches the roll's total duration exactly**, 260 ms either way.
- **`slideEasing` matches the roll's LEADING beat**, which is the one that
  carries the visible travel and the one an ease-out cubic describes. The
  residual difference is the last ~45 % of the curve: the roll eases *in* again
  as the bar sets down, a QML `NumberAnimation` does not. Reproducing it exactly
  would need a `SequentialAnimation` of two animations over one property (or an
  `easing.bezier`), which is not worth it for a drawer with only one moving edge
  — the roll's second beat exists because the bar changes DIRECTION, and nothing
  in the panel does.
- **`ViewMode.slideMs` is no longer a hand-copy** (hyprvtb 2.89). The roll's
  timing used to be a compiled-in `static constexpr` with nothing to read, so
  this was a literal with a comment asking whoever changed the C++ to remember
  this file — and it had already gone stale once. It is now the config key
  **`plugin:hyprvtb:slide_duration_ms`**, set in `hyprland.lua`, and the plugin
  publishes the resolved value to `~/.local/state/hyprvtb/motion.json` on every
  config reload. `ViewMode` holds a `FileView` on it with `watchChanges`, so
  `hyprctl reload` retunes a *running* panel — no restart, no polling, no
  process spawn. The `260` literal survives as the FALLBACK, for a session with
  the plugin disabled or quarantined after a crash, and must stay equal to the
  key's default in `hyprvtb/main.cpp`. (Unlike `Kinetic.friction`, which is
  still a genuine hand-copy of `plugin:hyprvtb:kinetic_friction` — the physics
  is re-derived Qt-side, so there is no single value to publish.)
- **Every duration goes through `ViewMode.ms()`, including the ones that are not
  the slide.** That function applies `SettingsStore.d.reduceMotion` (returns 0 —
  a `NumberAnimation` assigns immediately), then `animSpeed`, then the debug
  `animScale`. Those two settings had been in the Settings window driving
  nothing at all for their whole life, because every `Behavior` carried a
  literal. A literal duration now opts that widget out of the user's own
  settings, not just out of the house style.
- **A `Timer` that guards an animation is derived from it.** Five of them exist
  only to outlast a slide (unmapping a layer surface after the card is off it,
  holding a `_closing` flag through the animation it gates). The form is
  `ViewMode.ms(ViewMode.slideMs) + 20`: a fixed frame of margin that must NOT
  scale, or `reduceMotion` leaves no margin. They were 260ms literals against a
  220ms slide — right by accident, and wrong at every `animScale` but 1.

**The queue drawer has no animation of its own** (see below — both attempts were
bugs), so `DockTile`'s `Behavior on y`/`height` **is** the drawer's slide. That
is why those two Behaviors were the ones that had to move: at 200 ms the player's
queue opened visibly quicker than a window rolling out next to it, which is the
report that produced this section. Anything derived from that glide is derived
from `slideMs` too — `MediaContent`'s `closeHold` is `slideMs + 20`, never a
literal, or the drawer is released before the tile has finished handing its rows
back and the artwork balloons for the last frames of the close.

**Deliberate non-participants** — do not "fix" these to 260:

- **Anything tracking the pointer animates at all only under protest.** The
  bar's width settle (`shell.qml`, 200 ms) is the tail of a *gesture*, gated on
  `!dragging || snapping`; it is the drag's own snap, not a slide between rest
  states. See "Never animate, quantize, or re-zone a live drag".
- **Crossfades and hover feedback are not slides.** The layout crossfade and the
  askpass scrim (140 ms), the grip highlight (120 ms), the VU bars' 25 ms
  follow: an opacity or a level, with no travel to read.

---

## Four screen edges, and only two of them take a dock

`barEdge` is `left | right | top | bottom`. The first two are the vertical bar
everything here was written around; the other two lay the same bar across the
screen. **The axis is decided in ONE place** — `ViewMode.barHorizontal` /
`ViewMode.barAtStart` — and every consumer reads those rather than re-deriving
the edge (`shell.qml`'s `bar.hz`, `WallpaperLayer`, `EdgeAccent`, `EdgeGrip`,
`OsdWindow`, `NotificationWindow`).

**Dock mode and the shortcut notch are vertical-only, and neither is
special-cased downstream.** `ViewMode.dock` is false on a horizontal edge, so
`liveWidth` is simply `Theme.barWidth` and the grip unmaps; `NotchModel.shown`
is false, so `protrusion` and `slabH` are 0 — which is the no-notch case every
consumer (the exclusive zone, `NotchSeam`, `Launcher`'s face offset) already
handled. The runner still opens on its keybind; with no notch it comes out of
the screen edge instead of the panel's face.

**The classic layout has a second form, not a rotation.** `classicRow` in
`shell.qml` is its own Item: the vertical children each anchor into a stack, and
a layout that flips axis by ternary on every anchor is unreadable. The WIDGETS
are shared — `Taskbar`, `Tray`, `StatusPanel`, `Clock` and `DateDisplay` each
take a `horizontal` flag and change their own positioner — so there is one of
each on screen and no behaviour is duplicated. `Taskbar`/`Tray`/`StatusPanel`
are `Grid`s for exactly this reason (`columns: horizontal ? 999 : 1`), which is
also why their children can no longer carry `anchors.horizontalCenter`: a Grid
owns both axes, and `horizontalItemAlignment` does that job instead.

`StatusPanel._cy` returns -1 on a horizontal bar — every module shares one
scene-Y there, so the popups bottom-anchor rather than centre on a module.

## Two view modes, and the drag handle IS the switch

`ViewMode.qml`. `classic` is the 48px vertical bar this config has always had,
with the desktop widgets pinned out on the wallpaper. `dock` turns the panel
into a wide column (14–33% of screen, default 15%): `DockHeader.qml` (task icons
flowing across and wrapping, uptime at the right — hideable, `dockHeader`, which
takes its divider with it) over `DockGrid.qml`
(the widget grid). There is no toggle button — you grab the bar's inner edge
(`EdgeGrip.qml`, instantiated per screen in `shell.qml`) and pull. The grip's
strip and its hover highlight follow the inner-edge border — shortcut-notch
detour included — and fall back to the straight full-height strip while the
runner drawer is out (the drawer's Overlay surface is below the grip's, so a
strip over the notch would steal the open drawer's clicks).

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

### The shortcut notch

`DesktopNotch.qml` — the slab that protrudes from the bar's inner edge, centred
on it, holding a column of small program icons. It is instantiated INSIDE the
bar's own layer surface (`shell.qml`), not in a surface of its own, so the
notch's accent outline and the bar's inner-edge strip live in one coordinate
space and cannot drift apart during a width drag. Three pieces have to move
together, and all three are in `shell.qml`:

- the surface's `implicitWidth` (`ViewMode.maxPx + notch.width` — still a
  constant, which that comment requires),
- the input `mask`, which needs a second `Region` for the notch or its icons
  take no clicks,
- the inner-edge accent strip — UNCUT even where the notch crosses it; the
  notch's slab is drawn over it and hides the stretch behind its mouth
  (cutting it into two segments left an unpainted block at each corner).

`NotchModel.flushOn(screen)` is the ONE test for "is a window up against the
notch on this screen" — the seam paints over the join and the notch shifts its
seals for it (`columnInsetFlush`, centred between the window's border and the
panel's), and the two must never disagree. Do not grow a second copy of it.

`NotchSeam.qml` is its companion and **the only surface this panel puts above
windows** (`WlrLayer.Top`, empty input mask): a bar-background strip that hides
the window border + the notch's own border where a flush window meets it, so the
two read as connected. It is visible only while a frame is flush AND spans the
notch, from `WinState.frames` — window FRAMES (content + `2 * bar_width` of
hyprvtb titlebar + border). Two things the notch's outline depends on, both paid for once: the bar's accent
strip segments run INTO the notch's horizontal borders by a border width rather
than stopping against them (abutting shapes round independently at a fractional
scale and left an unpainted block exactly where the corner should be), and the
seam patch covers the notch's INSIDE only — covering its full height painted out
the ends of its own top and bottom borders, i.e. the corner pieces where the
outline meets the window's border.

**`WinState` has TWO fast paths, and the second one is not optional.** The
compositor announces windows opening, closing and going fullscreen — and NOTHING
for a geometry change. hyprvtb's maximize is a plain resize+move on a floating
window (`vtbDeco.cpp`'s `toggleMaximize`), so the transition the notch's seam
exists for produces no event at all and used to wait on the 1s poll: [his] "it
seems only sometimes does it happen as quick as it needs to". So
`scripts/win-watch.py` holds Hyprland's request socket open-and-closed at 120ms
and prints the client list ONLY when it changes; `WinState.applyClients()` is
the entry point it feeds, and the 1s `hyprctl` poll now only carries the monitor
half. Measured: a pure geometry change lands in ~130ms (was ~1100), a maximize
in ~30ms, an unmaximize in ~165ms — all inside the 260ms animation. Cost 0.3% of
a core. **Do not put that poll in QML with `Quickshell.Io.Socket`**: Hyprland
closes the connection after every reply and Quickshell logs a `PeerClosedError`
for each one, which is five lines a second into the log the panel is diagnosed
from.

A refresh asked for while one is in flight is REMEMBERED (`_pending`), not
dropped — a burst of events used to lose the one carrying the state that
mattered.

`HyprEvents.qml` keeps `WinState` up with the compositor: `hyprctl clients`
reports a window's GOAL geometry rather than its animated one (measured), so a
refresh driven off the event socket makes the seam appear and vanish as an
animation STARTS instead of a poll tick later. Hyprland emits nothing for a plain
geometry change, so a floating window dragged off the notch still waits for the
1s poll; `fullscreen`, `open/closewindow` and friends are events and are
instant. It is behind a Loader, not an import, so a Quickshell built without the
Hyprland module loses the fast path rather than the panel.

**NEVER PUSH FROM THE PER-RELOAD TREE INTO A SINGLETON.** This cost the same
regression twice: `DesktopNotch` published its size into `ViewMode` with a
`Binding`, a reload builds the new tree and THEN tears the old one down, and the
outgoing notch wrote its dying value (0 — its item goes invisible during
teardown) over the incoming one's. The panel then reserved nothing for the notch
and a maximized window covered the icon bar completely. `restoreMode:
RestoreNone` does NOT fix it — the binding is live until destroyed, so it is the
last EVALUATION that writes the zero, not the restore. The fix is structural:
`NotchModel.qml` is a singleton that derives the content and the metrics from
things that outlive a reload (settings, `DesktopEntries`, `Theme`), and
`ViewMode.notchPx` / `notchH` are `readonly` pulls from it. Nothing writes.

Two traps in the seam itself: `height` on a
`PanelWindow` whose `visible` depends on that same computation is a circular
dependency that silently reads the default 100px (use the ShellScreen's), and
the reserve is a border less than the panel's face, so the frame lands on
`face + windowBorderWidth`, not on the face.

`NotchModel.gap` is the ONE spacing unit — top, bottom, left, seal-to-seal, and
out to the panel's widgets — and it is measured from the outline's INNER edge to
the seal's own box every time. Two traps it was written around: the vertical
inset used to be measured from the slab's outer edge and the horizontal one from
the border's inner edge (so equal constants drew unequal), and the layout unit
used to be a 32px hit-target cell with the 22px seal inside it, which put two
pointer margins between every pair of seals and one against each edge. The
column is the width of a seal; the hover chip is drawn around it.

Membership is the `Keywords=bespoke;` tag on the desktop entry, the same test
`Launcher.qml` PARTITIONS on — never a hardcoded list. Toggle:
`desktopIcons` (Settings → appearance → shortcut notch). Launch goes through
`NixPath.launch`, never `entry.execute()` — see NixPath for the cgroup reason.
The notch publishes its protrusion as `ViewMode.notchPx` and the bar's
`exclusiveZone` reserves it, so a tiled or maximized window stops at the notch;
a floating window may still cover it, as it may cover the bar. docs/DESIGN.md
§12.2.2 is the rule.

### The runner IS the notch, pulled out — a DRAWER (`Launcher.qml`)

One rigid card, built at full size, whose only animated property is `x`. The
panel's face is a clip (`frame`), so everything not yet pulled out is behind it:
closed, the only thing this side of the edge is a `NotchModel.protrusion`-wide
strip that IS the notch; open, the seals have travelled out and their names and
the runner have come out from behind the panel after them. docs/DESIGN.md
§12.2.4 is the rule, and it records the two rejected attempts — a card sliding in
beside the notch, then the slab growing outward — because each of them is what a
"tidy-up" here would reinvent.

- **NOTHING RESIZES OR FADES.** No animated `width`, no animated `height` ([his]
  "it should not grow in height"), no opacity ramp on the revealed content. The
  reveal is the clip. If content needs to fade in to look right, the geometry is
  wrong.
- **CLOSED IT MUST BE THE NOTCH, to the pixel** — `closedW` is
  `NotchModel.protrusion`, the height is `slabH`, the seal inset is the notch's
  own, flush case included via `NotchModel.flushOn(screen)`. The surface maps and
  unmaps behind that identity, so there is nothing to see at either end; any
  disagreement is a visible twitch at the start of the pull.
- **The drawer's height is the seal column's height**, so the runner list gets
  whatever `slabH` comes to (~290px at nine seals). With `desktopIcons` off
  there is no notch to match, so it falls back to a plain 300px card coming out
  of the panel's edge.
- **It is its own Overlay surface, and that is forced.** The notch is inside the
  bar's surface so their outlines share one coordinate space during a width
  drag; a drawer this wide cannot be, because the bar's surface width is the
  constant the exclusive zone derives from. Its panel-side edge sits on the
  panel's face (`margins.right: 0`) and it covers the notch for as long as it is
  out — Overlay is above the bar's `Top`.
- **THE SURFACE IS NEVER UNMAPPED, and that is a bug fix, not an optimisation.**
  Mapping it per open flashed the drawer at the TOP-RIGHT for a frame every few
  opens ([his] "after every like 5 or so times"): a layer surface gets its
  anchors, margins and size by CONFIGURE, and a first buffer committed before
  that round-trip lands is drawn at the anchored corner with default margins —
  up and to the right, for this window. A race, so it misses most of the time,
  and `no_anim` took away the fade that used to cover it. So `visible: true`
  always; `out` (open, or the card still travelling) gates the CARD's `visible`,
  the input mask and the keyboard focus. `mask: Region {}` while in — the same
  clickthrough idiom `NotchSeam.qml` uses — or the window is a 401x960 dead zone
  over his desktop that also swallows the notch's hover tooltips.
- **`out` must track the CARD, not `open`** — `open || |x - closedX| > 1` — so
  the closing pull plays to its end before the card stops being drawn, and the
  keyboard is handed back only once the drawer is home.
- **THE SURFACE'S PLACEMENT IS THE OTHER HALF OF THE ILLUSION, and it is not
  where you would expect.** The bar's exclusive zone reserves the bar AND the
  notch (`liveWidth + notchPx - windowBorderWidth`), so a surface anchored to
  that screen edge is placed at the NOTCH'S OUTER FACE — the drawer lands beside
  the notch, never over it, and its closed strip reads as a second copy of the
  notch spawning next to the real one. It is cancelled with a negative margin of
  exactly what the zone added (`-(notchPx - windowBorderWidth)`). Measured on
  book: reserved 359 of 1536, panel face at 1209, unmargined surface edge 1177.
- **An UNMAPPED layer surface has no size.** `parent.height` is 0 while the
  drawer is closed, so centring the card on it put it at y = -161 against the
  notch's 319 — it mapped that high and settled afterwards ([his] "its currently
  higher than the bar itself"). Centre on `launcher.screen.height`, and ROUND
  it: the notch rounds its own (fractional logical pixels at 1.67 scale), and
  half a pixel out is half a pixel of not-being-the-notch.
- **The MAP must not fade, and that is a compositor rule, not a QML one.**
  `layersIn`/`layersOut` are enabled with `style = "fade"` (hyprland.lua), so
  opening faded the drawer up over the notch and closing faded it out — [his]
  "i can still see the transistion between the unrolled and rolled bar". A
  `hl.layer_rule` with `no_anim` on `^qs-launcher$` is what makes the map
  invisible; edit `hyprland.lua`'s nix source and rebuild — the switch
  reconciles the live copy. Nothing here can
  fix this from the QML side.
- **The name column is MEASURED** (`measureNames()` + `TextMetrics`), not a
  constant — a constant is dead space between the names and the runner for every
  seal set but the one it was picked for. Do it IMPERATIVELY: stepping a
  `TextMetrics` through the list inside a binding makes the binding depend on
  the `width` it is stepping through, and QML floods the log with binding-loop
  warnings for `nameW`.
- **The key does NOT spawn a process.** `RunnerShortcut.qml` claims
  `quickshell:launcher` over hyprland-global-shortcuts-v1 and the bind is
  `hl.dsp.global("quickshell:launcher")`; the old
  `exec_cmd("qs ipc call launcher toggle")` forked a shell and exec'd
  Quickshell's CLI on every tap — 20-30ms measured on book before the panel
  heard anything. It is a Loader like `HyprEvents.qml` because
  `Quickshell.Hyprland` is optional, and `qs ipc call launcher toggle` still
  works as the scriptable path. Check the claim with `hyprctl globalshortcuts`;
  the appid:name there, in `RunnerShortcut.qml` and in `hyprland.lua` must
  agree, and a shortcut nothing binds is silently inert.
- **A `{ release = true }` bind makes the client see a RELEASE, not a press.**
  Hyprland's `global` action sends whichever event the KEY was in
  (`ConfigActions.cpp`: `sendGlobalShortcutEvent(..., m_passPressed)`;
  `KeybindManager.cpp`: `m_passPressed = pressed`), so the bare-Super tap — which
  MUST be a release bind or every Super chord opens the runner — dispatches at
  key-up and `onPressed` never fires. That is a dead key with nothing wrong
  anywhere you would look: the shortcut registers, the bind exists, `hyprctl
  globalshortcuts` lists it. `RunnerShortcut.qml` handles both signals, with a
  250ms coalesce so a press-type bind's pressed+released pair cannot toggle
  twice.
- **Probe the protocol half without touching his keyboard**:
  `hyprctl eval 'hl.dispatch(hl.dsp.global("quickshell:launcher"))'` runs the
  action outside a keybind (`m_passPressed` is -1, so the client gets `pressed`)
  — it proves the appid:name and the delivery, not the key path. Disconnect the
  toggle first, or the probe opens the runner on his screen.
- **Opening does no scanning.** The runner's corpus — every non-seal,
  non-`NoDisplay` entry, sorted, each with its lowercased name AND its alias
  haystack — is a binding on `DesktopEntries.applications.values`, so it is
  rebuilt when the SYSTEM's programs change, not per open and not per keystroke.
  `rebuild()` only filters it. (And `onOpenChanged` must not both clear the box
  and call `rebuild()`: clearing already rebuilds through `onTextChanged`.)
- **`Name` is not what he types.** gimp's entry is called "GNU Image
  Manipulation Program", so a name-only search found nothing for `gimp`. Each
  corpus row carries `aliasOf(entry)` beside the name — generic name, desktop id,
  the executable's basename, the entry's own `Keywords` — and `rebuild()` scores
  in three tiers: name-prefix, name-substring, alias. The tiers exist so an alias
  hit can never outrank the program actually called that.
- **An empty runner is an `XDG_DATA_DIRS` problem, not a search one.**
  `DesktopEntries` scans that variable, and the panel inherits it from the
  systemd USER MANAGER, which is not a login shell. On `book` the manager's copy
  is Fedora's three dirs and nothing else, so every nix-profile program
  (nicotine+ among them) was invisible — and its icon unresolvable — while the
  same list was complete in any terminal. `quickshell.nix`'s `panelEnv` wrapper
  appends the two nix profile dirs if they are missing; `top` already has them
  system-wide. `qs ipc call launcher query <text>` prints `corpus=` first for
  exactly this reason: 0 or a short corpus is that bug, `hits=0` is this one.
- **What is left is not ours.** The bind fires on RELEASE — that is what makes a
  bare Super tap distinguishable from Super-as-a-modifier — so the human hold
  time is in the path and no code here can take it out. Firing on press would
  open the runner on every Super chord.
- **Check the SEARCH without opening it** — `qs ipc call launcher query gimp`
  prints the corpus size, the hit count and the first eight names in draw order.
- **Check it without opening it** — `qs ipc call launcher geom` prints the card's
  y/height beside the notch's own arithmetic plus the edge gap. `cardY==notchY`,
  `cardH==slabH`, `edgeGap==0`. Opening it to look is not available: it is on his
  screen and it takes the keyboard.
- **The two columns partition, they don't filter.** `bespoke(entry)` is the same
  keyword test `NotchModel` uses; the runner list drops every entry that passes
  it, so no program is on the card twice and none is missing.
- **A `Behavior` needs a writable property.** `readonly property int inset: …`
  loads as `Invalid property assignment: "inset" is a read-only property` — a
  bound `property int` animates fine and is still driven by its binding.

**There is no runner button** — `RunnerButton.qml` is deleted, and neither the
classic bar's top cluster nor `DockHeader` has one. The only way in is
`qs ipc call launcher toggle`, bound to mainMod+Super in `hyprland.lua`. Don't
grow a second entry point without asking.

### Every program icon goes through `AppIcon.qml`

Runner rows, task cells, tray items and a toast's header all draw one, and none
of them draws it itself. `AppIcon` whitens the cached source before tinting, so
the supplied state colour is exact for every icon, not only white `currentColor`
seals. The paired `oxygen-live-0`/`oxygen-live-1` theme generated by
`home/srvs/wal-files/oxygen-live-icons.py` recolours Oxygen's whole `base/`
tree — folders, files, devices, apps and actions — from the current wallpaper
accent and alternates the theme name to flush KDE's icon cache in open programs.

**Verify a change here on the sandbox output** (`tools/sandbox.sh` + `qs -p
<test shell.qml>`, then read the pixels back): `QT_QPA_PLATFORM=offscreen` has
no shader path, so MultiEffect renders nothing there and an offscreen grab will
"confirm" whatever you already believe.

It tells the two apart by name, through the generated `AppSeals.qml` singleton —
`Quickshell.iconPath` returns `image://icon/<name>`, never a path, so there is
nothing to look at on disk. That list comes from `my.appSeals`, declared in each
app's module beside the `home.file` that installs its svg (see
`home/prog/app-icons/seals.nix`). **A new bespoke app declares its seal there or
its icon renders red.**

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

### The toplevel list has no MONITOR, and the sandbox's promise depends on one

`tools/sandbox.sh` gives agents an off-screen headless monitor so nothing they
open reaches the user's screen. It hides the window's *pixels*. It does nothing
about the **Wayland foreign-toplevel list**, which carries appId, title and
activated and no output at all — so every agent test window appeared in the
user's taskbar, for the whole life of the sandbox. He reported it, having watched
programs he did not launch come and go in his bar.

**`WinState` owns the answer and everything that walks the toplevel list must ask
it: `WinState.offOutput(appId, title)`.** It already polls `hyprctl -j monitors;
hyprctl -j clients` for roll-up and minimize, so the monitor is free — the same
shape of problem (the compositor knows, the protocol does not) answered from the
same poll. Three consumers today, and a fourth is a bug waiting to happen:

| consumer | why it must filter |
|---|---|
| `TaskCell.qml` | `visible: !offOutput(...)`. Both hosts are Positioners (Taskbar's `Column`, DockHeader's `Flow`), so an invisible cell leaves no gap |
| `Media.playerUp` | the queue socket is per-user — a sandbox player would put an agent's queue in the dock |
| `Askpass.active` | the bar would dim for a dialog that is nowhere on his screen |

- **The discriminator is HARDWARE IDENTITY, not the name.** A monitor is physical
  if it has a non-zero physical size or any of make/model/serial/description;
  a headless output has none (measured: DP-5 reports a make, model and serial,
  530x300mm — HEADLESS-6 "" and 0x0). The user may attach a **second real
  monitor** one day and its windows must still appear, which is exactly what
  keying on `HEADLESS-` alone would get wrong the first time it mattered. That
  name is ORed in as corroboration only: it can add a virtual output, never
  subtract a real one, since no DRM connector is ever named it.
- **The join is fail-VISIBLE.** A class+title key counts as off-screen only when
  EVERY mapped client under it is on a virtual output. Two windows of one app
  with the same title are indistinguishable here (above), and hiding one of the
  user's own windows is far worse than showing one of an agent's for a poll.
- **`WinState.screenIsVirtual(shellScreen)`** is the same question asked of a
  `Quickshell.screens` entry, for a per-monitor widget that has no window to ask
  about. It is deliberately SYNCHRONOUS — it reads `name`/`model`/`serialNumber`
  off the screen object and never waits on the poll, so anything gated on it is
  correct in the first frame of a reload rather than absent for it.
- `tools/sandbox.sh` additionally TAGS every window it launches (`tag +sandbox`).
  That is the discriminator for "whose window is this" — it survives the window
  being moved — where the monitor answers "can he see it". The panel filters on
  the monitor on purpose: a sandbox window that ends up on the real screen is
  something he should be able to find and close.

**A grid on a monitor he cannot see must not MEASURE either.** `DockGrid` takes
`gen: -1` when `screenIsVirtual(screenRef)`, and `ViewMode.reportTile` refuses a
negative generation. There is one grid per monitor and one `tileInfo` singleton,
so whichever completes last wins the table — while a sandbox monitor was up,
`qs ipc call live tiles` answered about a panel on a screen nobody was looking
at, at a different height (`tasks got=433` against a true 451), with nothing in
the output to say so. Same rule as everywhere else here: a measuring instrument
has to be harder to poison than the thing it measures.

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

**`settings.json` is also the desktop's ONE settings channel into `apps/`**, and
that is why it holds keys nothing in this directory reads. `apps/pylib/
deskstyle.py` watches the file and publishes it to the apps as the `DeskStyle`
context property; `scrollbarStyle` (docs/DESIGN.md §9.2) is the first key with
**no panel consumer at all** — the panel draws no scrollbar anywhere — and it
still lives here, because one channel with an unused key beats a second channel.
Put the next desktop-wide appearance setting in the same place, and add its
control to `SetPgAppearance.qml` beside the font and motion ones.

### Volume is NOT one of them — WirePlumber already remembers it

`SysInfo.volume` is a **mirror of the default sink**, not a stored setting:
`adjustVolume`/`setVolume` write through `wpctl set-volume` and
`scripts/sysinfo.sh` reads the level back every poll. Do not add a `volume` key
to `SettingsStore` and do not re-apply a saved level at startup — WirePlumber
persists it per machine, in a file that does not sync between the hosts:

    ~/.local/state/wireplumber/stream-properties   sinks/sources with no device
                                                   route (every virtual/filter
                                                   sink) + application streams
    ~/.local/state/wireplumber/default-routes      devices that DO have routes
                                                   (ALSA cards, bluez)

Both hosts run stock WirePlumber restore hooks (`hooks.stream.state`,
`hooks.device.routes.state`), and a level set through the panel is on disk
within a second or two, so it survives a logout and a reboot on its own. A
second copy in `settings.json` would be a shared-across-machines value fighting
a machine-local one. **Brightness is the opposite case** — no daemon remembers
it, so the panel has to — which is exactly why the two must not be treated as
one feature. `tools/volume-persist-test.sh` proves the restore path on
whichever host runs it, from a private pipewire instance that never touches the
session graph; `docs/volume-persistence.md` has the measurements.

#### "No sound, but the panel looks like audio is playing"

Reported on `top`, 2026-07-30. Diagnosed to the default sink being **MUTED**;
nothing in this repo had done it, and the two things that looked guilty were not:

- **MUTE IS PER-ROUTE, and it survives a reboot with nothing in this repo
  recording it.** `default-routes` stores one entry per ALSA route, so
  `…:output:analog-output-lineout={"mute":true, …}` mutes the speakers while
  `…:output:analog-output-headphones` stays unmuted at its own level. Neither
  the panel nor `settings.json` holds a mute anywhere — **`wpctl set-mute` is
  written in exactly one place in this repo**, the `XF86AudioMute` bind in
  `../hypr-files/hyprland.lua`; `SysInfo.muted` and `Osd.muted` only ever READ
  it. So when sound is gone, `wpctl get-volume @DEFAULT_AUDIO_SINK@` first, and
  do not go looking in the panel for a writer that does not exist.
- **`wpctl set-volume` does NOT unmute**, so raising the level through the
  panel on a muted sink changes a number and nothing else. The OSD is honest
  about it (`x` instead of a level, empty fill) — keep it that way.
- **The VU meter and the spectrum keep moving while the speakers are silent,
  and that is correct.** Both cavas capture a **monitor port**, and on both
  hosts apps play into `easyeffects_sink` — which is *upstream* of the hardware
  sink's mute. `audio-active.py` counts sink-inputs for the same reason and is
  read-only. So "bars are moving" says a client is producing audio, never that
  anything is reaching the speakers; the mute is said in `StatusPanel`'s `vol`
  row (`Theme.crit`) and the VU's level line, which is the only place to read it.

Confirm the graph before blaming a level: `pw-link -l` shows the whole chain
(`mpv → easyeffects_sink → ee_soe_* → alsa_output.…analog-stereo`), and a break
there is a different bug from a mute.

### Brightness IS one of them — nothing else remembers it

Both halves of the range are live STATE in `settings.json` (machine-local, so
`top` and `book` keep their own): `gammaLevel` for the negative region and
`brightnessHw` for the hardware level, both written by `SysInfo` and by nothing
else. `brightnessHw` is `-1` until the user first moves brightness through the
panel — then the machine came up however it came up and we leave it alone.

**The restore takes the FIRST poll tick rather than following a read**
(`SysInfo._restoreBrightness`), because a read that lands first sets
`brightness` from the hardware and the restore is then indistinguishable from
drift. It is skipped entirely when `restoreState()` ran, i.e. on a reload: the
live level came across with the rest of the state, and on `top` re-driving the
hardware costs a 1.5s DDC write every reload. Imperative code at startup reads
the store through `SettingsStore.loadNow()` — measured here, a fresh tree sees
the shipped default (`stored=-1`) for the first tens of ms.

Neither the kernel nor the monitor is a store we control: book's backlight is
only written back by `systemd-backlight@` on a **clean** shutdown, and top's
level is whatever the Dell kept in its own NVRAM over DDC.

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
  `pgrep -a cava`: **two while audio is playing and ZERO while it is not**, ever
  — the VU and the media spectrum — however many monitors are attached.
- **Both cavas are gated on audio actually playing** (`SysInfo.audioActive`,
  `scripts/audio-active.py`). Unconditional they cost **~19.5% of a core
  continuously with nothing playing** — 11.4% themselves, plus they doubled the
  panel's own CPU animating bars at 60fps and multiplied wireplumber's by ~40x
  serving two monitor captures. Measured before and after on book: 36.2% -> 15.5%
  (`docs/perf-cpu-hotspots.md`). On a laptop that is battery spent drawing
  silence.
  - **The obvious test is always true here — do not "simplify" it back.** Any
    un-corked sink-input exists permanently, because EasyEffects holds one for
    its convolver output (`effect_output.*`). Apps play into `easyeffects_sink`,
    so the effect chain's own nodes must be excluded before counting. A gate
    written the naive way never fires and looks correct.
  - **It is event-driven** (`pactl subscribe`), not polled; the 15s re-check is
    only a backstop for a missed event.
  - **The lifecycle sites use `Qt.binding`, never a bare `= true`.** Assigning
    true from the crash-retry timer would break `running: audioActive` for good
    and cava would never stop again — the gate silently undoing itself after the
    first respawn.
  - **Stopping zeroes the levels** rather than leaving the last frame frozen: a
    stale bar is indistinguishable from a live one.
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

### Watching `top` from `book`: `TopStats` + `TopProcDrawer` (book-only)

The dock's system-info tile on **book** has a disclosure directly UNDER the local
graphs — `top v` — that rolls out a COPY of top's OWN square-card grid (cpu, gpu,
mem, net, load, vram, swap, fan) sourced from the other machine, `top`, so the
laptop can keep an eye on the desktop. It is gated on `Host.name === "air"`
everywhere and does nothing on top itself. Same two-halves split as above, plus a
transport:

- **`TopStats.qml` is the data singleton**, shaped exactly like `SysInfo` and
  exposing the SAME property/method surface `MetricCardGrid` reads (the full set
  of ring buffers — cpu/gpu/mem/swap/net/load/vram + per-fan `fanPctHist`, plus
  `fmtSize`/`fmtSpeed`, plus inert `psi*`/`dsk*`/`battery*` for the hidden
  substitute cards; `intervalSec`, a `watch(obj, on)` set, a
  `stateJson`/`restoreState` pair carried by `shell.qml`'s `persist` block). It
  fills those buffers by **ssh to the MagicDNS name `top`**, running
  the SAME `scripts/sysinfo.sh` and parsing the same positional pipe line — so a
  new field added to `sysinfo.sh` must keep `TopStats.parse`'s indices in step
  just like `SysInfo`'s (see "sysinfo.sh's fields are POSITIONAL"). The transport
  is **`/usr/bin/ssh`, not a nix ssh** (nix binaries can't resolve MagicDNS on
  book), through `sh -c` for `$XDG_RUNTIME_DIR` expansion, with
  `BatchMode`+`ControlMaster`+`ControlPersist` so 2s polls reuse one connection
  and a missing key fails fast. **No new listener** — an outbound tailnet ssh,
  the same loopback/tailnet-only rule as the comfy tunnel. **`ConnectTimeout`
  only bounds the initial handshake, not a session request over an
  already-established master** — measured live, a poll wedged on a stale mux
  socket (book sleeping/waking) for 19h with `reachable` frozen and nothing in
  `qs log`. `ServerAliveInterval=5`/`ServerAliveCountMax=2` plus a local
  `timeout 15` backstop bound the recovery instead.
- **`MetricCardGrid.qml` is the shared card block** — the 4x2 square-card grid,
  extracted from `TaskManagerContent` so book's own tile and this mirror of top's
  cannot drift apart. It takes `src` (a SysInfo-shaped object — `SysInfo` for the
  local tile, `TopStats` for the mirror), `noGpu` (the card set: false = the
  gpu/vram/fan set top has, true = book's psi/io/batt substitutes) and
  `wheelTarget` (the fan card's brightness scroll — **null** on the mirror, so
  scrolling top's fan card never moves book's backlight, and top's `SysInfo` would
  be the wrong target anyway).
- **`TopProcDrawer.qml` is the view + disclosure**, animated like the media queue
  drawer (`SettingsStore.d.topStatsOpen`, a clip whose height glides over
  `ViewMode.slideMs`, `Behavior` gated on `!ViewMode.settling` so a reload with
  the drawer open lands in place). `TaskManagerContent.qml` places it directly
  under the local graphs on air only (`top: cards.bottom`), height 0 off book;
  the process table below runs to the tile bottom, so opening the drawer reflows
  the LIST down rather than eating its bottom. It rolls out the same
  `MetricCardGrid` sourced from `TopStats`, so it presents at exactly the size
  top's tile draws the block at. It lived under `CpuContent` in the cpu corner
  popup until 2026-08-09, then under the process list until it moved beneath the
  graphs and grew from one cpu chart to top's full grid.
- **The open-state caret is a MIRRORED `v`, never `^`** — More Perfect DOS VGA
  has no triangle glyph and its `^` sits against the ascender and clips a strip
  this short (the same finding as MediaContent's queue chevron), so the button
  draws `top` + a `v` flipped about its own centre with a `Scale`.
- **It polls ONLY while the drawer is both on screen AND expanded** — `wantData`
  drives `TopStats.watch` (`active` is now the dock tile's visibility, not the
  popup's `open`), so a closed disclosure spawns no ssh and top is never touched
  when nobody is looking.
- **`reachable` fails VISIBLY** (docs/DESIGN.md §10.2): an overlay says
  "connecting to top…" (never reached) or "top unreachable" (was, isn't) instead
  of a blank chart. Live data needs book joined to the tailnet with key-based ssh
  to top; until then the drawer honestly reads unreachable and nothing is broken.

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

**The screenshot overlay short-freezes visible tooltips.** The full-screen
`Screenshot` overlay (`Meta+Shift+S`) maps on top of the bar and steals the
pointer, so a hover-driven tooltip retracts the instant the hotkey fires — before
the capture. `Screenshot.qml` holds `TooltipState.frozen` (a `pragma Singleton`)
from overlay-open, through the capture settle, then releases it; `Tooltip.qml`
keeps its chip out while frozen and finishes the retract when the freeze lifts.
Any new tooltip surface that wants the same grace reads `TooltipState.frozen`.

### The dock grid is ONE PAGE, and must stay one

`DockGrid.qml` is `columns` x `rows` (4 x 29) filling the panel exactly: the row
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
reporting alongside. Measured with a per-tile id in the log:

- **Construction and teardown lay a tile out at a degenerate size** (`h=-87
  want=-1` inside a parent -185px tall). Nothing true can be said about a tile
  that is not on screen. This is the cause that actually poisoned the table.
- **More than one grid reports under the same keys at once**, and the reload is
  NOT where that comes from. It is one grid PER MONITOR — a leftover
  `tools/sandbox.sh` headless output is enough — each of which takes its own
  `nextGen()` and therefore *wins* the table from the other, at a different
  panel height. Check `hyprctl monitors` before trusting a surprising number.

**What a reload does NOT do is leave old trees running.** The surface handoff is
real and load-bearing, but it is a handoff of the *surface*, not an overlap of
two ticking trees, and the earlier note here claiming "the old tree keeps ticking
— timers and all — for a while after" was wrong. Measured on book by putting a
2 s `Timer` + a random per-instance id into the live `Theme.qml` (a singleton, so
exactly one instance per engine generation) and tallying the log across **19
generations**: every generation stopped ticking *before* its successor was even
constructed — `ticks_after_successor_born = 0`, nineteen times out of nineteen.
Process-level over 12 forced reloads: RSS 130.9 MB → 153.7 MB immediately after
→ **120.7 MB** three minutes later (below where it started), fds 68 → 91 → 77,
inotify watches 123 → 125, `pgrep -c cava` never above 2. Nothing accumulates,
so there is no per-reload ghost tree, no doubled polling and no idle battery cost
to chase. **Five "distinct grids across four forced reloads" is just five
sequential generations appearing in a cumulative log**, times however many
monitors are attached — count what is ticking inside a WINDOW, never how many
distinct ids the whole burst printed.

So `DockGrid` takes a GENERATION from `ViewMode.nextGen()` at completion and
stamps every report; older generations are dropped, a newer one wipes the table
first, and non-positive geometry is refused outright. The instrument shows one
panel — the newest — or nothing, never a mixture. On a multi-monitor desktop
"the newest" means whichever MONITOR's grid completed last, which is a different
panel height; the numbers are still self-consistent, just not necessarily the
screen you are looking at. `DockTile` re-reports
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
- **CPU% is SOLARIS MODE — a share of the WHOLE MACHINE, 0-100.** It is divided
  by the CPU count, so a row reads against the cpu card above it, which is
  computed from whole-machine total-vs-idle deltas and has always been 0-100.
  Until 2026-07-27 it was **Irix mode** — a share of ONE core, `top`'s default,
  which the `I` key toggles there — so a multithreaded process legitimately
  reported up to 1600% on this 16-thread box next to a gauge saying 100. Two
  percentages on one screen with two denominators and nothing on screen saying
  so; `docs/DESIGN.md` §10.5 is the general rule. The count comes from
  **/proc/stat's `cpu[0-9]` lines**, not `os.cpu_count()`: those are exactly the
  CPUs summed into the aggregate `cpu` line `sysinfo.sh` feeds the gauge, so the
  two are comparable by construction. Never hardcode it — book has a different
  core count.
- **The colour thresholds moved WITH the denominator**, and that is the half
  that silently rots. 50/10 were half and a tenth of one core; left alone they
  become 3.1 and 0.6 machine-percent here and paint an idle desktop amber. They
  are now machine shares (crit 25, warn 5), chosen so a pegged single-threaded
  process — `100/NCPU`, 6.2% on top, 12.5% on book — still colours. The column
  keeps ONE decimal: at 44px it is 5.5 cells, so `100.0` fits and `100.00`
  clips at full load.
- **Don't trust `comm` for the name.** The kernel caps it at 15 characters and on
  NixOS everything runs through a wrapper, so it reads `.quickshell-wra` /
  `.claude-wrapped`. The script prefers `argv[0]`'s basename — except for
  Chromium/QtWebEngine helpers, which rewrite their entire command line into
  `argv[0]`, so a "name" containing spaces or over 24 characters falls back.
- **The `[x]` is SIGTERM on left click; everything else a process can be asked
  to do is on RIGHT-CLICK anywhere in the row** (`ProcMenu.qml`): filter by
  name, copy pid — separator — suspend/resume, lower priority — separator — end
  task, force quit. SIGKILL
  used to be the right-click on the `[x]` itself, so that an unrecoverable
  action was never one mis-timed left click away on a table that re-sorts under
  the cursor every 2s. The menu keeps that guarantee — it is still two
  deliberate acts — and removes the trap that appeared once right-click meant
  "menu" everywhere else: a right-click a few pixels off would have SIGKILLed
  whatever had just sorted under the pointer.
  **That order is part of the guarantee, not a style choice** (docs/DESIGN.md §7.2,
  §10.3): the destructive pair is LAST and behind a separator, so the entry the
  pointer lands on is read-only. It shipped the other way round — `End Task` and
  `Force Quit` first — for the menu's first day.
- **The menu is ONE instance at the table root, not one per row.** The list
  `reuseItems` and re-sorts every 2s, so a delegate-owned popup would be
  destroyed or silently re-pointed at another process while it was open. It
  captures pid/name/state/nice on open and binds to nothing live; the row is
  used once, to place it. It anchors LEFT like `TaskMenu.qml`, dismisses on
  hover-out (this config never imports `Quickshell.Hyprland`, so there is no
  focus grab), and `TaskManagerContent` closes it explicitly when the widget
  goes inactive or is destroyed — nothing else unmaps a popup surface.
- **The panel is in its own process table, and it is not offered a way to end
  itself.** Its row draws no `[x]`, the menu replaces the signalling entries
  with `this is the panel - signals refused`, and `Procs.signal()` refuses
  `Quickshell.processId` a second time at the call site. The bar, the wallpaper
  and every popup are one process; there is no undo and nothing left on screen
  to explain what happened.
- **An action `execDetached` cannot report on must not be OFFERED.** There is no
  exit code and no stderr, so signalling or renicing another user's process is a
  perfect silent no-op. `proc-list.py` therefore reports `mine` (owner uid ==
  ours) alongside `state` (`T` = suspended, which picks Suspend vs Resume) and
  `nice` (Lower Priority disappears at 19, since niceness is one-way without
  privilege); a row that is not ours gets the read-only entries and a line
  saying why. Those three fields are **appended** — the parse indexes
  positionally and tolerates the older five-field shape carried across a reload.
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
- **The `fan` card is EVERY fan in the box, one line each** — the chassis and
  cooler fans from hwmon plus the GPU fan, which used to have the card to
  itself. There is no longer a separate horizontal chassis-fan bar; it was one
  averaged number, and an average is the wrong summary here (one fan pinned at
  2400 with four idling reads identically to five fans working moderately, and
  it is the pinned one you can hear). `Fans.qml` is the derivation —
  headline, per-line colours, the series, and the tooltip — and it is a plain
  `QtObject` rather than a singleton **on purpose**: it is pure derivation over
  `SysInfo.fans`/`fanPctHist`, which is what lets `tools/fan-harness.sh` drive
  it offscreen against synthetic fan sets. Keep it free of Quickshell imports.
- **What the percentage IS, and what it is not.** The card's readout is the
  fastest fan going as a share of *its own* full scale. For the chassis fans
  that is the **commanded pwm duty** (`pwm/255`), NOT a fraction of maximum RPM
  — sysfs publishes no maximum, so there is no honest denominator for one and
  we do not invent it. For the GPU it is nvidia-smi's reported speed. That is
  the only axis both sensors can share, and the lines are *not* comparable in
  air moved or noise. **A fan with no percentage anywhere is not plotted at
  all**: it keeps its tooltip row with its exact RPM, because putting it on a
  0-100 axis would mean inventing that denominator. Exact speeds live in the
  tooltip and are never rounded into the axis.
- **A fan is listed only when it TURNS (`rpm > 0`), whatever its pwm says.**
  The rule was "rpm > 0 OR duty commanded" first, reasoning that a fan being
  driven while reading 0 rpm is stalled and worth surfacing. This board
  disproves it: `top`'s **nct6687** (driver `nct6683`, not `nct6775` — that one
  does not probe this EC at all; no `acpi_enforce_resources=lax` was needed)
  publishes **ten** `fan*_input` and eight `pwm`, of which exactly **four**
  headers have a fan (fan1-4); the other four sit at 0 rpm with 23-100% duty.
  So a nonzero pwm over a dead tachometer is an *empty header* here, not a
  fault, and the first rule showed eight fans on a machine with four. sysfs
  offers nothing that tells the two apart.
- **The PUMP is not drawn AT ALL, and the test is history, not level.**
  [his] *"exclude the pump that one i cannot change even via the mobo settings
  and im pretty sure i cant even hear it anyway"*, then *"i also meant just
  completely remove the pump fan from the widget. i dont need to see it at
  all"*. So `Fans.fixed()` governs VISIBILITY: an excluded fan has no line, no
  tooltip row and no part in the readout. It hides a fan only when it is at
  maximum duty **AND** has never once been seen to move (`SysInfo.fanVaried`,
  sticky and carried across a reload). **Both halves are load-bearing**: "at
  maximum" alone would delete a chassis fan ramped to 100% in a thermal event,
  which is the moment it matters most; "not moving" alone hides everything,
  since at idle all four duties here are rock steady across a 20s sample.
- **The two guards matter MORE now the consequence is a blank card.** Nothing is
  judged under `settleSamples` (30 = 60s), so a fresh panel hides nothing; and
  if the rule would hide every fan it draws them all, because an empty card says
  less than a card full of constants. Override by hand with `fanShowFixed` in
  `settings.json`; there is no Settings-window control.
- **Hiding the pump means a pump failure has no indicator — so a fan that STOPS
  comes back, and it is LOUD.** `sysinfo.sh` lists a fan only while it turns, so
  a dead fan would simply vanish and, with the pump already invisible, leave the
  desktop entirely. `SysInfo._setFans` re-emits any name that stops reporting as
  an `rpm: 0, stopped: true` row; at 0 rpm the hide rule cannot catch it, so it
  is always drawn and marked `STOPPED`.
- **`FanAlarm.qml` is the alarm, and it is a PURE STATE MACHINE** — no Theme, no
  Quickshell, no timers, driven one `update()` per poll by `SysInfo`. That is
  what lets `tools/fan-harness.sh` replay whole failure episodes offscreen,
  which is the only way this is ever exercised: a real pump stop cannot be
  staged and must never be staged on the live machine. It lives in `SysInfo`
  rather than in the widget **on purpose** — a pump failure must notify whether
  or not the task manager is open.
- **Three guards, each paid for by something real; four of the harness's six
  alarm cases are things that must stay SILENT.**
  - `!fanVaried` — only a fan that has never changed duty. A fan the machine
    controls has a line on the card, so its stopping is already visible.
  - `hist >= settleSamples` — it must have RUN for a minute first. `fan5` here
    spins ~20s then reads 0 for ever; a header that twitches once is not a fan.
  - `fanHadRpm` — it must have had a TACHOMETER. The GPU fan reports a percentage
    and no RPM, so "0 rpm" is its normal reading; without this an `nvidia-smi`
    hiccup would announce a dead graphics-card fan.
- **30 seconds of sustained zero (`alarmPolls` 15) before it fires, once per
  episode, reset on recovery.** A false alarm costs more than a late one — it is
  never trusted again — and a CPU that loses its pump throttles long before it
  is damaged, so the alarm need not win a race. `stoppedFor`/`alerted` are
  carried across a reload, or a wallpaper change would restart the count and
  re-fire a toast already shown.
- **The toast is `notify-send -u critical -t 0`**, like every other toast this
  repo raises. Urgency 2 is doing four jobs the panel already implements —
  `soundCritical` instead of the balloon, DND bypass, exemption from eviction,
  no auto-expiry — and `-t 0` states the last explicitly now the panel honours a
  stated timeout. The harness asserts those flags are still in the argv, because
  losing one would silently downgrade a pump failure to a 5-second balloon with
  nothing failing. It does NOT send a live toast: an agent's test notifications
  have already had to be cleared off his screen by hand once.
- **The card says it too** (`SysInfo.fanAlarm`): the readout goes `Theme.crit`
  and the secondary reading is replaced by the fan's name. Said twice per
  docs/DESIGN.md 3.5 — the toast may have been dismissed hours ago, and the fan it is
  about is the one the card deliberately does not draw, so there is no line to
  go crit and no row to dim.
- **The lines are a BRIGHTNESS LADDER, not different colours** (`Fans.shade`).
  The wal palette is one hue by construction, so there are no distinguishable
  hues to hand out — see `docs/DESIGN.md` 3.1/3.3. It stays legible to ~5-6 fans;
  past that it degrades to "two lines look alike" rather than to an unreadable
  widget, because the tooltip names every fan with its exact speed in the same
  order.
- **Mainline exposes no `fan*_label` on this chip**, so the names are `fan1`..
  `fanN` — deliberately not the `CPU_FAN1`/`PUMP_FAN1` names LibreHardwareMonitor
  infers from the same registers, which are unverified against the physical
  board. Render whichever channels are nonzero; never assume an index means a
  particular header.
- **Scrolling the fan card is screen brightness**, through
  `SysInfo.adjustBrightness` — the same function the `bri` status row and the
  `XF86MonBrightness` keys use, so all three share one debounce, one OSD and one
  continuous range (hardware to 0, then the gamma layer below it). `MetricCard`
  carries a generic `onWheelUp`/`onWheelDown` pair for it, notch-based via
  `WheelNotch`, with multi-notch bursts collapsed rather than replayed so a
  flick cannot stack ~1.5s DDC writes.

```bash
qs ipc call live fans          # per fan: rpm, pct, and its history length
qs ipc call brightness status  # level/hw/gamma/floor/backend, without driving it
./tools/fan-harness.sh         # sysinfo.sh + Fans.qml against synthetic fan sets
```

  `live fans` is the only way to check this card without looking: the readout is
  a summary and the lines are a squiggle, so neither says whether the right fan
  is on the right line. A `hist=0` is a line that is not being fed.
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
  and it gives it back. `shell.qml` sets `WlrLayershell.keyboardFocus` on the
  bar (in dock mode): `Exclusive` for the one-frame PRESS grab
  (`Procs.filterGrab`), else `OnDemand` while `Procs.filterFocus ||
  Procs.filterLatch`, else `None`. Three halves, all load-bearing:
  - **HOVER does not arm it, and changes nothing about focus at all.** Hyprland
    grants an on-demand layer surface the keyboard on the next pointer MOTION
    over it — measured in a nested compositor, not on a click
    (`processMouseDownNormal` only calls `refocus()` when the press lands on a
    *window*) — and a None→OnDemand commit grants nothing either. So a bar that
    went OnDemand the moment the pointer reached the box *was* the "hover steals
    focus from the window" report. The surface is made focusable only by a
    **PRESS** on the box, which takes the keyboard through the one mode a commit
    can switch to that grabs it outright — `Exclusive` — then settles back to
    `OnDemand` the instant the box holds focus (`filterFocus`), restoring the
    click-into-a-window hand-back.
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
    did. So the latch, set together with the press that grabs, holds the surface
    focusable until the pointer leaves the **bar** (a passive `HoverHandler` on
    `barBody` clears it), and the hand-back happens with the pointer over a
    window — the case the compositor gets right. Repro harness: a nested Hyprland
    plus a probe layer surface, driven by `hl.dsp.cursor.move` and read back
    through each surface's own `activeFocus`. `hyprctl activewindow` is **not**
    an instrument here: it reports `CFocusState::window()`, which
    `rawSurfaceFocus` never clears, so it keeps naming a window that has not had
    the keyboard for minutes.
  - **OnDemand once focused — never sticky-Exclusive.** Exclusive keeps sending
    us the keyboard after the user clicks into a window, so their next keystroke
    would go to the filter box instead of what they just clicked on. That is why
    the Exclusive state is only the one frame that makes the click grant
    anything; the moment the box holds focus it is back to OnDemand, which hands
    the keyboard back as part of the click into a window.

  **"Click anywhere outside the box and it stops taking keystrokes" has THREE
  cases, one per kind of thing that can be under the click, and each is
  somebody else's:**

  | under the click | who handles it | where |
  |---|---|---|
  | the PANEL | us — a click inside a layer surface moves no focus at all, so the compositor never hears about it | the catcher on `barBody` (`shell.qml`): `Procs.blurFilter()` then `mouse.accepted = false`, so the widget underneath still gets its click |
  | a WINDOW | the COMPOSITOR, and it is already right | the pointer merely ARRIVING over a window revokes this layer's keyboard; Qt clears the TextInput's `activeFocus` with it and `onActiveFocusChanged` does the rest. No click needed, nothing to add |
  | the WALLPAPER | us — and this was the missing one | the catcher in `WallpaperLayer.qml`, same shape as the bar's |

  The wallpaper case is the bug the user reported as "I have to click back in
  the bar to get rid of the caret": `processMouseDownNormal` only calls
  `refocus()` when the press lands on a **window**, so a press on a Background
  layer surface moves no focus, and with `filterFocus` still true the bar went
  on offering `OnDemand` forever. It is fixable in-process only because the
  wallpaper is *our* surface — there is no channel through which the panel could
  see a click on somebody else's.

  **Handing the keyboard back from the wallpaper is the SAFE direction**, which
  is why that catcher can drop focus outright where the bar's cannot:
  `refocusLastWindow` searches only the OVERLAY and TOP layers, so it does not
  find a Background surface under the pointer and falls through to the last
  focused window. Measured on the event socket: `activewindow>>,` for 2 ms, then
  the window. Contrast `filterLatch` above, which exists because the same
  transition with the pointer over the PANEL strands the keyboard on nothing.

  **That 2 ms of `activewindow>>,` is a pothole, not a destination, and
  anything on this machine that reacts to focus events has to treat it as
  one.** It is the only path on this desktop that publishes "focus is on
  nothing", and it is always immediately followed by the window that had it.
  Reacting to it is not free: `kitty-focus-dim.py` greyed kitty's text on the
  empty event and restored it on the next one, and because each step is a
  subprocess (`kitty @ set-colors`, plus an `hyprctl -j clients` to resolve the
  window) a 3.5 ms gap on the wire became **38 ms of visibly grey terminal** —
  measured end to end in the nested harness. It now waits `NOTHING_GRACE`
  (150 ms) before believing an empty payload. Note what this rules out: the
  flash was NOT hyprvtb's titlebar and NOT Hyprland's border, which flip on the
  same 3.5 ms boundary and cannot render a frame inside it. If a new consumer
  of `activewindow` ever flashes, debounce the empty payload before you go
  looking at the compositor.

  The widget clears both flags when it goes inactive or is destroyed: a stale
  `filterFocus` would leave the panel holding the keyboard with nothing on screen
  to type into. The filter text is deliberately NOT in `SettingsStore` (it is a
  question you are asking now, not a preference) but IS carried across a reload
  in `Procs.stateJson`.

### The media seekbar scrubs on the WHEEL too

One detent moves the seek by 5% of the track — the number is
`../hyprvtb/vtbDeco.cpp`'s `VTB_PLAYBAR_SCROLL`, so scrubbing a titlebar and
scrubbing this bar cost the same gesture. A **fraction**, never seconds: the
widget plays 90-second interludes and hour-long mixes. Three things it encodes,
all of which the plugin had to learn first:

- **`WheelNotch`, never a sign test.** A trackpad is ~125 Hz of sub-pixel
  deltas; per-event stepping threw the song forward by minutes in the titlebar
  copy. Its `maxSteps` clamp is also the debounce — a separate timer would
  either drop the notch you ended on or leave the fill behind the wheel.
- **`seek.pending` is what the bar SHOWS** until the player's position catches
  up (or 1.5s passes). Its real job is not the redraw but the *accumulation*:
  without it every notch of a burst re-derives its step from a position up to
  500ms stale, so three fast notches move the song by one. It is bounded so a
  source that reports `canSeek` and then ignores `SetPosition` cannot leave a
  lie on the bar.
- **The wheel rides the same `enabled: seek.seekable` gate as the click**, so
  an unseekable source keeps its arrow cursor and the notch falls through —
  the same shape as the lyrics list's click-to-seek. The fill is *not* dimmed
  there: it is a reading, and it is still true.

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
- **Lyrics come down the SAME socket, and only when asked for.** MPRIS has no
  lyrics field of any kind and `LyricsProvider` lives inside the player process,
  so the queue line gained a `lyrics` object for whatever is playing:
  `{source, synced, lines:[{t,line}], text}`. Two halves matter.
  **It is a subscription** — the panel writes `LYRICS 1` while
  `Media.live && Media.queueOpen` and `LYRICS 0` otherwise, because resolving is
  not free on the player's side (tag reads, an LRCLIB request, and a writeback
  into the file), and an unopened drawer must not turn every track the user
  plays into a fetch. It is **edge-triggered**: the server answers every
  `LYRICS` line with a fresh snapshot, so re-sending it on the 5s reconnect tick
  would re-parse the whole queue twelve times a minute. `Media._sentWant` is
  what makes it edge-triggered, and it resets to -1 on a disconnect because the
  server holds the subscription per CONNECTION — a player restart drops it.
  **The FOLLOWING is ours**, not the player's: whole timed lines arrive once per
  track and `Media.lyricIndex` binary-searches them against our own MPRIS
  position, so the lit line owes nothing to socket latency. That is also why the
  position re-emit `Timer` runs at 200ms instead of 500 while a box is on screen
  — that tick is what moves the line, and at 500ms it lands visibly late.
  An older player omits the field entirely, which reads as "no lyrics" and
  leaves the drawer exactly as it was — the fallback that has to hold on `book`
  between a `git pull` and the next player relaunch. Lyrics are `Glyphs.px()`-ed
  at INGEST like the queue rows, once per push: apostrophes are not rare in song
  lyrics and one U+2019 clips the line it is in.
  Regression test (no GUI, isolated `XDG_RUNTIME_DIR`, so the live player's
  socket is untouched): `apps/player/tools/queue-lyrics-test.py`.
- **The lyrics BOX is a parallel copy of `apps/player/qml/LyricsView.qml`** —
  `docs/DESIGN.md` §5.4 owns the look and the §20 row records what the panel's copy
  drops. It lives inside `queueBox`, takes 42% of the drawer's inner width as a
  FRACTION (never a pixel budget standing in for a character count, §2.7), and
  hides the artist column while pushing the durations left against its 1px
  divider. **It adds no height anywhere**: `naturalRest`, `implicitHeight` and
  the tile's reported `wants` are untouched, which is what keeps the weather tile
  below from moving.

- **A derived `bool` is coerced with `!!` AT THE SOURCE, and read with
  `=== true`.** JS `&&`/`||` yield the last VALUE, not a boolean, so
  `lyrics !== null && lyrics.synced` was `undefined` whenever the payload had no
  `synced` — and a `property bool` bound to undefined logs "Unable to assign
  [undefined] to bool" on every evaluation. The consumers additionally test
  `=== true` for a reason that is not paranoia: **a rebuild swaps the store
  symlinks file by file, so for one reload the panel can run a NEW
  MediaContent.qml against the OLD Media.qml**, where the property does not
  exist at all. Observed live, three bindings, once. Same rule for guarding a
  dereference — `Media.lyrics ? Media.lyrics.text : ""`, never
  `Media.hasLyrics ? …`: they are separate bindings over the same push and QML
  gives no ordering between them, which threw a real TypeError on the frame a
  track lost its lyrics.

  ```bash
  ./tools/media-lyrics-probe.sh    # 30 assertions, ~15s, nothing on screen
  ```

  That is the regression test for all of it, and for the fallback: it drives the
  REAL `Media.qml`/`MediaContent.qml` with socket-shaped queue lines — including
  an OLD player's, with no `lyrics` key at all — and asserts the column
  collapses, the artist stays at `w=75`, the duration stays at `x=299`,
  `implicitHeight` is 230 either way, and no binding ever takes undefined.

  **How that was verified, because it generalises to any widget here.** Copy
  this directory to a throwaway config, replace the data singletons it names
  with stubs (here `Media` and `SysInfo` — a dozen properties each), give it a
  `shell.qml` that is one `FloatingWindow` around the content component, and run
  it under an isolated `HOME` with `QT_QPA_PLATFORM=offscreen`:

  ```bash
  HOME=$P XDG_CONFIG_HOME=$P/.config XDG_RUNTIME_DIR=$P/run \
    QT_QPA_PLATFORM=offscreen qs -p $P/.config/quickshell/shell.qml --no-duplicate
  ```

  No sandbox monitor is needed and nothing reaches a screen. The isolated `HOME`
  is not optional: `SettingsStore` would otherwise write the user's live
  `settings.json`. Walk the tree from the root and `console.warn` real geometry
  — that is how the row layout above is a measurement rather than a claim
  (durations `x=299 → x=147` at 350px wide, artist `w=0 vis=false`, and
  `implicitHeight`/`naturalRest` identical with and without lyrics). One caveat:
  an isolated `HOME` loses the user font, so absolute line heights in the probe
  are a fallback font's, not More Perfect DOS VGA's — read the ratios, not the
  pixels.
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
  20px): the same twenty points and night bands drawn thinner, because at that
  size it is the labels and markers that stop being readable, not the line, and
  the line is what the forecast is for — **and no hover cursor**: a full-height
  rule over a ~22px canvas is a third of the widget, and the legend it would be
  pointing at is not drawn in this tier either, so the MouseArea stops tracking
  while `condensed` and the cursor block is gated on `!mini`. Bare header only, below that — the graph
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
  asking for that form is asking for the room it needs. **It buys that room in
  whole ROWS** (35.3px on this panel) — there is no smaller unit, so a few
  pixels either side of a row boundary decide whether the forecast takes two
  rows or three, and "shrink the condensed forecast a little" has exactly one
  available step. `minMiniGraph` 24 demanded three rows (97.9px of tile) and
  left the drawer three; 20 fits in two (62.6px of tile = 60.6px of content
  against a 58px minimum, the miniature still drawn at 22.6px) and gives the
  drawer its fourth row back. The cap is legal only because
  `q` is not in `placements`.
  **A floor mirrored from a content component must add the TILE'S FRAME**
  (`DockGrid.tileInset`, 2px): the number reserves a tile, but what has to fit
  is `DockTile`'s Loader, anchored `margins: 1`. Without that term the forecast
  spent its whole life one and a half pixels short — two grid rows = 62.6px of
  tile = 60.6px of content against a 62px minimum — so `miniGraph` was false,
  the graph was dropped entirely and the "condensed" forecast was the
  bare-header tier that exists only for panels with no room at all. The comment
  above claiming the drawer went four rows to three was describing what the
  arithmetic was meant to do, not what it did.
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
  - On the close the flag flips in one frame while the tile takes a full slide
    (`ViewMode.slideMs`, 260ms) to shed
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
  break. **That glide IS the drawer's slide** — the drawer has no animation of
  its own — so it runs at `ViewMode.slideMs`/`slideEasing`, the desktop's
  canonical 260ms OutCubic taken from the window roll. See "One slide, one
  duration"; `closeHold` is derived from the same constant.

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

**`elide: Text.ElideRight` is the exception — do NOT hand-roll an ASCII
elide.** Qt substitutes three ASCII periods by itself when the family has no
U+2026, so an elided `PixelText` never takes the ascent hit above. Measured
offscreen against the real font at 15px: `TextMetrics.elidedText` came back
`"a very long tr..."` (`0x2e 0x2e 0x2e`), and the rendered pixels are identical
to a hand-written `"..."` — same rows, same ink. A truncate-and-append helper
would only re-implement it worse, and the font is monospace (advance exactly
8px at 15px, so `implicitWidth == 8 * length`) if you ever need to do the
arithmetic for something else.

**But an ELIDING `Text` may never be asked for its own `implicitWidth` to
decide its `width`.** `width: Math.min(implicitWidth, <cap>)` is the standard
shape for "as wide as the text, capped" and it is a binding loop: a `Text` with
`elide` lays out against the width it was given, and until something has asked
it for its implicit width it publishes the ELIDED width as `implicitWidth`.
Which of the two evaluates first at construction decides whether it converges
or spins, which is why it fires in bursts and not every time — the queue
drawer's artist column logged 27 `Binding loop detected for property "width"`
inside one panel generation, one per realized row. **Nothing looks wrong when
it happens**: the loop settles at a width that is merely a little short, so
`qs log` is the only place it exists. Measure with a **`TextMetrics`** instead —
it has no geometry of its own, so there is nothing to feed back, and
`advanceWidth` is the unelided `implicitWidth` to the pixel with this font
(measured: 67.5 and 286.875 for two sample strings, identical both ways).

```qml
TextMetrics { id: nat; font: label.font; text: label.text }
PixelText { id: label; elide: Text.ElideRight
            width: Math.min(nat.advanceWidth, parent.width / 3) }
```

It is the same rule as the zero-size popup above — an implicit size must be
computed only from things that do not follow the item's own size — one level
down, on a single `Text`. `MediaContent.qml` has both of its instances fixed;
**`ProcMenu.qml`'s `MenuRow` label and `WeatherContent.qml`'s place label still
carry the old shape** and neither has been observed to spin, so they are latent
rather than broken. `ProcMenu`'s in particular is not a drive-by fix: that
popup MEASURES its entries' `implicitWidth` in `openFor()` and refuses to open
on a degenerate result, so the two have to be changed together or not at all.

**A PAIR of ASCII glyphs is not a pair of arrows. Draw one glyph and mirror
it.** There is no triangle either (`▲ ▼ ▴ ▾`, like `↑ ↓`, are all absent), so an
up/down affordance has to come out of ASCII — and `^` is not `v` upside down
here: from the glyf table `v` is 1792 units tall sitting on the baseline while
`^` is 1024 units hard against the ascender. In the media widget's 14px roll
handle that put the caret's ink on rows 0-2, on top of the hover hairline and
reading as *outside* the button, against rows 4-10 for the `v`. Both states are
now the same `v` with a `Scale { yScale: -1 }` about its own centre. **Round the
item's `y` when you do this** — an integer origin maps pixel centres onto pixel
centres, so `Text.NativeRendering` stays crisp under the flip; a half-pixel
origin antialiases it back into the mush `PixelText` exists to avoid.

**That rule covers hardcoded UI strings. Text that comes from OUTSIDE — track
tags, window titles, filenames, notification bodies, process names — cannot be
written to suit the font, so it has to be mapped on the way in instead.**
`Glyphs.px()` is that map: the glyphs More Perfect DOS VGA lacks (the
typographic punctuation `’ ‘ “ ” – — ‐ … − • ′ ″ ⁄ ﬁ ﬂ`, the exotic spaces,
the arrows, `™ © ® ℗`, `×` and `ø`) onto ASCII equivalents. Every widget that
draws text it did not author calls it — which is why it is its own singleton
and not the player's, where it started.

**Map at the INGEST point where there is one** (`Notifications.plain()`, the
`Procs` parse, `Media`'s queue), so it costs one pass per data change rather
than one per delegate on every scroll. Where the data belongs to a Qt or
Quickshell model this panel does not own — toplevel titles, `FolderListModel`
rows, `DesktopEntries` — map at the display site instead.

**It is DISPLAY ONLY, and that is a safety rule, not a stylistic one.** Nothing
identifying may go through it: `TaskCell`'s raw title is the join key into
`WinState` and the address the click dispatches on; `FileBrowser`'s `path` and
`selected` are handed to `gio`/`mv`/`rm`; `Procs`' pid is what `kill()` signals;
`Launcher`'s `entry.command` is the argv. Two prefill sites are the sharp edge —
`FileBrowser`'s rename dialog and `DiskContent`'s inline label editor both put a
value in front of the user that is then written back by `mv` and by
`Disks.relabel()`. Map either and the panel quietly renames the user's file or
their filesystem. Both carry a comment saying so; leave them.

It is deliberately a lookup table, not "strip anything the font lacks": 427 of
the 11k tracks in the library carry U+2019 and 140 carry U+2010, but ~830 have
CJK or fullwidth titles with no ASCII form at all, and a title turned into
question marks is worse than one drawn in the wrong font. Those still sit low;
fixing them needs a pixel font with CJK coverage.

**Audit the hardcoded half by asking the FONT, not by eye.**
`QRawFont("…/MorePerfectDOSVGA.ttf").glyphIndexesForString(ch)[0] == 0` is the
test (`fc-list :charset=` and `QRawFont.supportsCharacter` both lie — the
latter answers `True` for characters it maps to glyph 0). Run it over every
string literal in this directory; it found fifteen the day it was written, in
`Cheatsheet`, `SetSelect`, `SetPgWidgets`, `Lock`, `Screenshot` and others.

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
  hyprvtb titlebar is a strip `totalBarW() = bar_width * 2` thick on ONE of the
  window's four edges (`plugin:hyprvtb:titlebar_edge`, default right —
  `DECORATION_EDGE_RIGHT`, `desiredExtents` right = 64px, the same side the
  panel is on, so client-rect math leaves exactly the titlebar covered, the bug
  reported on 2026-07-26). Reconstruct the frame from
  `plugin:hyprvtb:{enabled,bar_width,titlebar_edge}` +
  `general:border_size` via `hyprctl getoption -j` (`enabled` is a global
  bool, not per-window). A left/right bar adds to the frame's WIDTH on its own
  side; a top/bottom bar adds to its HEIGHT and contributes nothing to the
  width arithmetic.
- **`bar_width` is ONE column of two, and that is the trap.** The bar is
  double-wide — `totalBarW() = bar_width * 2`, the inner column the app's own
  buttons and the outer one the system controls — so a reconstruction that adds
  `bar_width` covers half of it and looks almost right. `Screenshot.qml`'s
  "window" mode shipped with a hardcoded `+ 32` and cut the outer bar off every
  window shot (reported 2026-07-29). **Every consumer of the frame rect reads
  those four keys** — there are two now, this script and that one — and no
  consumer writes a pixel literal.

  The two other things a captured frame needs, in `Screenshot.qml`: it is
  CLIPPED to the output (a frame may reach past the screen edge, where `grim -g`
  captures nothing) and a degenerate result is refused outright rather than
  handed to `grim`. The bottom-left drop shadow is deliberately **out** — it
  falls ON the desktop, so including it would put a strip of whatever is behind
  into the shot. Measured, not reasoned: a kitty at `718x805` in
  `tools/sandbox.sh` drew ink out to local column 783 = `718 + 64 + 2` (diff
  the sandbox monitor with and without the window, and read the column
  profile), with the top edge at `client.y - 2`.

---

## A toast's OWN `expireTimeout` outranks the panel's default

`notifTimeoutMs` (5 s) is the *server default*, i.e. what a notification gets
when it sends `expire_timeout -1`. `NotificationCard.qml` must honour the two
cases where the sender said otherwise, per the freedesktop spec: **`0` means
never expire** and **`>0` is an explicit lifetime in ms**. It did not, and that
is a bug with a compounding failure mode rather than a cosmetic one.

**A progress toast is ONE notification morphed in place** — `notify-send -p` to
learn its id, then `-r <id>` on every update (surfer's downloads,
`filer/videoconv.py`'s compress). Quickshell's server reuses the object for a
known `replaces_id` and, per `server.cpp`, does **not** re-emit `notification`
— so no new card, no second sound. But the moment our timer expires it, that id
leaves `idMap`, and the next `-r` names nothing: `Notify` falls through to the
`new Notification` branch and opens a **brand new toast, with its own sound**.
Every whole percent. The user's report was "longer downloads just trigger the
toast over and over instead of staying on the screen until they are finished."

Three halves, all of which have to hold:

- **The card honours `expireTimeout`** — `persistent` (critical *or*
  `expireTimeout === 0`) suppresses the timer; otherwise the interval is the
  notification's own value, falling back to `Notifications.timeoutMs`.
- **A replacement RESTARTS the countdown.** The card is not rebuilt, so an
  ordinary toast updated in place would otherwise still die on the original
  arrival's clock. `Connections` on `summaryChanged`/`bodyChanged` restarts it.
- **`maxVisible` eviction spares `expireTimeout === 0`**, exactly as it spares
  critical. Evicting a live progress toast puts its sender straight back in the
  loop above. The `victim || vals[0]` fallback still bounds the stack.

**Senders: a toast you intend to keep updating must ask for it** — `-t 0` on
every progress update, and the *default* timeout on the completion/failure one,
which has nothing left to update. Both app-side callers do this now.

Measured, not reasoned — two `notify-send -p` lanes 8 s apart (past the 5 s
default), reading the returned id:

```
control (default timeout):  first=36  after 8s=37   <- NEW TOAST, the bug
persist (-t 0):             first=38  after 8s=38   <- same toast, replaced
```

That is the regression test: same id across a gap longer than `notifTimeoutMs`.
Close the persistent one afterwards (`busctl --user call
org.freedesktop.Notifications /org/freedesktop/Notifications
org.freedesktop.Notifications CloseNotification u <id>`) — by construction it
will not go away on its own. `gdbus` is not installed here; `busctl` is.

### Action buttons: the server advertised them for months and the card drew none

`NotificationServer.actionsSupported` has always been bound to the
`notifActions` setting, and `NotificationCard.qml` never rendered
`Notification.actions` — so an app that asked the server whether it could ship
buttons was told **yes** and then had them silently dropped. Whatever the
capability says, the card is what makes it true.

- **Buttons are a right-aligned `SetButton` row under the body**, sized to their
  labels (`minWidth: 52`, `maxWidth: 120`) rather than the settings pages' 96px
  floor — three of those do not fit a 300px card. Capped at three.
- **`default` is not a button.** Per the spec it means "the notification itself
  was clicked", so it rides the card's own MouseArea and pre-empts the plain
  dismiss.
- **Invoking does not close anything.** Quickshell's `invoke()` emits
  `ActionInvoked` and stops there; the card calls `dismiss()` itself. A sender
  blocked on `notify-send -w` gets the action key on stdout and exits.
- **`bodyRow` sits at `z: 1`, over the fill-the-card dismiss MouseArea** — which
  is declared last and would otherwise eat every button click. Text and images
  accept no events, so a click anywhere else still falls through to dismiss.
- **Rendering is gated on the same `notifActions` setting** the capability is,
  so the panel cannot draw a control the sender was told would not be there.
  A sender that needs the buttons should check the setting and offer a
  text fallback — `repo-updates` (`home/srvs/repo-updates.nix`) reads
  `settings.json` directly and names its CLI instead.
- **Except at urgency 2, which always draws them.** A critical toast is the
  level reserved for a question that has to be answered — `tools/heavy-gate.sh`
  asking whether to stop ComfyUI/ollama for a heavy rebuild — and one whose
  answer is drawn nowhere is the affordance-that-silently-fails DESIGN §10
  forbids. Note the asymmetry that keeps this honest: the card draws MORE than
  the server advertised, which loses nothing. The bug the gate exists to
  prevent is the other direction, advertising buttons and then swallowing
  them.

**Do not test this by firing a toast.** A notification is his screen; the
harness (`tools/repo-updates-test.py`) replaces `notify-send` with a log line,
and `repo-updates.py --demo` exists so that raising a real one with real buttons
is a command HE runs.

### A KDE Connect toast is titled with the PHONE, and only that one is

The card's header line is the sender's `appName` — except for a notification
relayed off his phone, where `appName` is the string `KDE Connect` on every one
of them and says nothing. `Notifications.sender(n)` owns that choice and
`NotificationCard.qml` just draws what it returns; nothing else in the stack
knows about it.

**The device name arrives in a HINT, and Quickshell drops hints it was not asked
for.** `NotificationServer.extraHints` is the opt-in: without
`["x-kde-origin-name", "x-kdeconnect-source-device"]` in it,
`Notification.hints` holds only the hints Quickshell has properties for and the
name is simply not there. That is silent — the header just keeps saying
`KDE Connect`.

Which hint carries what was **measured, not assumed** (26.04.3):

- `kdeconnect_notifications.so`, `Notification::createKNotification`, calls
  `KNotification::setHint` with `Device::name()` for **both**
  `x-kde-origin-name` (17 chars, upstream's device-name hint) and
  `x-kdeconnect-source-device` (26) — the latter is documented upstream as the
  device *ID*, so treat the name there as this build's accident, not a contract.
  `x-kde-display-appname` gets the phone-side app.
- `knotifications` forwards them: `NotifyByPopup::sendNotificationToServer`
  loops over `KNotification::hints()` unconditionally into the `QMap` it hands
  `Notify`. The server's advertised capabilities do **not** filter hints, so
  there is nothing to declare in `GetCapabilities` to earn them.

Three rules the implementation is built on:

- **Only KDE Connect's title changes.** `x-kde-origin-name` is a *general* KDE
  hint (KMail sets it to an account name), so the notification has to be
  identified as KDE Connect first — the `x-kdeconnect-source-device` hint being
  present, or `appName`/`desktopEntry` naming kdeconnect. Everything else keeps
  its `appName` untouched.
- **Never draw a raw device id, and never draw nothing.** If the candidate looks
  like an id (`>=16` chars of hex/`_`/`-`, which covers both forms kdeconnect
  issues) it is looked up in a table built from `kdeconnect-cli --list-devices
  --id-only` + `--name-only` — one `sh` line, zipped by index, **refused
  outright on a length mismatch** rather than zipped into wrong names. Until
  that lands the header falls back to `appName`. `kdeDevices` is reassigned
  wholesale so the card's binding re-evaluates when it does; the spawn is
  throttled to once a minute so a burst from an unknown id cannot fork per
  notification.
- **`kdeconnect-cli` is nix-only**, so it goes through `NixPath.sh` and is in
  `NixPath.launchTargets` — book's panel has a Fedora-only PATH.

Verify it without a phone and without touching his screen: copy this directory
to a throwaway config, add a `shell.qml` that prints `Notifications.sender()`
for every tracked notification, and run it under an isolated `HOME` **and an
isolated bus** — `dbus-run-session`, because the live panel already owns
`org.freedesktop.Notifications`:

```bash
HOME=$P XDG_CONFIG_HOME=$P/.config XDG_RUNTIME_DIR=$P/run QT_QPA_PLATFORM=offscreen \
  dbus-run-session -- sh -c 'qs -p $P/.config/quickshell/shell.qml --no-duplicate & …
    notify-send -a "KDE Connect" -h string:x-kde-origin-name:"Galaxy S22 Ultra" \
        -h string:x-kdeconnect-source-device:"Galaxy S22 Ultra" "Signal" "hello"'
```

**Put a stub `kdeconnect-cli` first on `PATH` when you exercise the id lookup.**
A private bus has no kdeconnect on it, so the real CLI *activates a second
`kdeconnectd`* — which advertises this box on the LAN under the throwaway `HOME`
and, measured 2026-07-29, **outlives the bus teardown** and has to be killed by
hand. The CLI's output shape is verifiable once against the live daemon; the
stub is what keeps the harness off the network.

### A `value` hint makes a toast a progress toast

An int 0-100 in the `value` hint — the de-facto progress hint every other
notification server reads, so `notify-send -h int:value:37` is the whole sender
side — makes `NotificationCard.qml` draw docs/DESIGN.md §8.1's bar under the
body, filled in the card's urgency tint. It is in `extraHints` for the usual
reason: Quickshell drops a hint nobody asked for.

Two things the sender owns, not the card. **Persistence**: a progress toast is
sent at `-t 0` and updated with `--replace-id`, because the card's expiry timer
would otherwise retire it mid-operation and the next update, naming an id the
server no longer holds, would open a fresh toast (the surfer-downloads bug,
§10.4). **Honesty about the fraction**: the card draws what it is given, so a
step with no countable denominator must ease and stop short of 100 rather than
sit at 0 or claim to be finished. `repo-updates` is the reference sender —
`home/srvs/repo-updates-files/repo-updates.py`, harness
`tools/repo-updates-test.py`. A bar-only update still restarts the card's
expiry (`onHintsChanged`), so a sender that *did* set a timeout keeps it fresh.

### An image-download toast thumbnails + opens the file

surfer's download **completion** toast for an image carries the downloaded
file's absolute path in the `x-download-image` hint (surfer's `Downloads.done`
threads the path through from `Main.qml`'s `onDownloadRequested` — `downloadDir
+ "/" + downloadFileName` — and only attaches it for a download whose extension
is in its `IMAGE_EXTS`, mirroring filer's). `NotificationCard.qml` renders a
48px thumbnail from that path and, because the whole card is the affordance,
clicking it `xdg-open`s the image (the default handler → viewer) before
dismissing. A non-image toast, or a progress toast (whose file is still
partial), carries no hint and clicks plain-dismiss. `x-download-image` is in
`extraHints` for the same reason the KDE Connect hints are — Quickshell drops a
hint it was not asked for.

The hinted path is **not trusted as the file's location**: `sort-downloads`
files finished image downloads out of `~/Downloads` into `~/Pictures` within
seconds (a .path unit on ~/Downloads), so a toast pointed at the ~/Downloads
path it was handed would render a broken thumbnail and `xdg-open` a file that
had already moved — that was the feature "not working". `NotificationCard.qml`
instead resolves the file's CURRENT location through `scripts/dl-resolve.py`
(the hinted path, then the media dirs with sort-downloads' ` (n)` collision
suffixes) for both the thumbnail and, again, at click time just before
`xdg-open`. That script is registered by `quickshell.nix`.

---

### Who gets a toast: one gate, modelled on Plasma's

`Notifications.onNotification` is the ONLY place that decides whether a
notification appears and whether it makes a sound. The shape is lifted from
Plasma 6's `kcm_notifications` / `plasmanotifyrc`, which splits the question
into global conditions and a per-sender rule; keeping the same split means the
settings page reads like the one he already knows, and the parts we *cannot*
do are visible as omissions rather than as invented alternatives.

The branch order, which is the whole specification:

1. **Learn the sender** (`_recordSeen`) — before any decision, so an app whose
   popups you switched off still has a row to switch them back on.
2. **`rule.popup`** — the sender's own switch, and it **binds even for
   critical**. Plasma's `ShowPopups` does the same. A toggle a notification can
   talk its way past is a dishonest control (§10).
3. **Urgency 0** vs `notifLowPopup` (Plasma's `LowPriorityPopups`).
4. **`dndNow()`** — suppress unless this sender has `rule.dnd`
   (`ShowPopupsInDndMode`), or it is critical and `notifCriticalInDnd` is on.
5. **The sound**, gated separately on `rule.sound` and `notifSoundMute`, so
   silencing a sender never costs you the toast.

Three things to know before editing it:

- **`dndNow()` is a function, not a property, and that is deliberate.**
  `notifDndUntil` is a wall-clock instant, and a binding over `Date.now()` never
  re-evaluates. Everything asks at the moment a notification arrives. The
  minute-timer beside it only *retires* a lapsed value so the Settings window is
  not left claiming a quiet hour that ended; the gate is exact without it.
- **A rule matches on EITHER of a sender's two names**, entry first
  (`keysFor`). The desktop entry and the app name disagree constantly — Vivaldi
  is `vivaldi-stable` / `Vivaldi`, and this desktop's own programs send
  `-a filer` with no entry at all — so matching one only would mean a rule that
  silently never fires, which is the exact failure this feature exists to
  prevent. `keyFor` (the first of the two) is the key a sender is *recorded*
  under; `ruleFor(n)` takes the notification, not a key.
- **The seen registry is one of four sources for the app list, not the list.**
  It stores a display name once, on first sight — never re-stamped, both to keep
  the panel off the disk during a burst and because the name a rule was made
  under should not shift under it.
- **`notifRules` / `notifSeen` are rewritten wholesale, never mutated.**
  `SettingsStore` diffs each key by `JSON.stringify` against its last-seen-on-disk
  snapshot; editing the object it handed back changes both sides of that
  comparison and the save finds nothing to write.

**What Plasma has and we deliberately do not**, so nobody "restores" it:
`ShowInHistory` (there is no notification history in this panel) and
`ShowBadges` (no taskbar badge), which is why the per-app row has three
switches and not five; the per-*event* table under a service (that exists
because KNotification apps ship an event catalogue in a `.notifyrc` — our apps
send plain `notify-send` and have none); and `WhenScreensMirrored` /
`WhenScreenSharing`, portal-level state nothing here reads. One default is
inverted on purpose: Plasma's `CriticalInDndMode` ships **off**, ours ships
**on**, because letting critical through is what this panel has always done and
quietly reversing it would lose an alert.

**Test it with `tools/notif-rules-test.sh`, never by firing a toast.** A
notification is his screen, and the failure mode here is *silence* — a wrong
branch does not throw, it eats a notification. The harness copies the shell
files to a temp dir and runs the gate and the settings page offscreen on a
private DBus session (private because these files include a notification
*server*, which must never contest the name his panel owns). It transcribes the
branch order above; reorder the real gate and you reorder the harness too.

`SetNotifApp.qml` is the per-app row — Plasma's master/detail pane will not fit
a 640px single-column page, so the app is a row and its rules are an indented
disclosure under it (docs/DESIGN.md §9.1).

#### The app list must be populated BEFORE an app interrupts you

A list you can only edit after the fact is useless exactly when you want it, and
the first cut of this got that wrong twice: first it listed only learned
senders, then it made up for that with a **hardcoded array of this desktop's
apps**. Plasma hardcodes nothing — it runs a `KApplicationTrader` query and
scans the `.notifyrc` dirs — and neither does this now. `SetPgNotifs.qml`
merges four sources, weakest label first so the best name wins:

1. **Installed `.desktop` files declaring `X-GNOME-UsesNotifications=true`**,
   found by `grep` across `$XDG_DATA_HOME` + `$XDG_DATA_DIRS`. `grep` and not
   `DesktopEntries` because Quickshell's `DesktopEntry` exposes the standard
   fields and not arbitrary keys; `KApplicationTrader` does the same scan behind
   a nicer face. **Measured on `top` 2026-08-07: zero of the 299 installed
   entries declared it** — a GNOME convention nixpkgs does not carry, which is
   also why Plasma's own list here is built almost entirely from its other two
   sources. So **this desktop's five notifying apps now declare it themselves**
   (`home/prog/{filer,player,painter,surfer,board}.nix`). Adding that one key to
   a new app is the whole of listing it; there is no second list to update, and
   Plasma's KCM picks them up too.
2. **`~/.config/plasmanotifyrc`** `[Applications][…]`, read once by a `Process`,
   best-effort — an absent file is simply no extra candidates. This is the one
   place on the machine that knows firefox, discord, nheko and vivaldi notify
   him, because Plasma learned it over months.
3. **`notifSeen`** — what the panel has learned since.
4. **The picker**: a live search over `DesktopEntries.applications.values`,
   adding any installed program by its `.id`. Needs no declaration from the app,
   so it cannot go stale, and it is the answer to "must I wait for it to
   notify". Adding writes the app into `notifSeen` and **no rule** — the row
   appears reading its inherited defaults.

**`.notifyrc` services, Plasma's other source, are deliberately not one here**:
31 are installed and every one is a Plasma/KDE internal (`kwin`, `powerdevil`,
`akonadi_*`, `plasma_workspace`) that a Hyprland session never runs — 31 rows of
noise for zero real senders.

**`panelSenders` is the one list left, and it is four entries** — `quickshell`,
`screenshot`, `recording`, `nix`. These are three panel features and a user
service, not applications: they have no `.desktop` file to declare anything, and
the name each uses exists only as the `-a` argument at its `notify-send` call
site, so nothing can enumerate them. **Keep it in step** — `grep -rn
'notify-send' apps home` finds every call site.

**A sender whose `-a` name and `.desktop` id disagree must send the
`desktop-entry` hint.** goetia is the only one: the program is `goetia`, the
entry is `board.desktop`. Without the hint the scan offers a row keyed `board`
while the notification arrives as `goetia`, and the rule silently never fires —
so `board-notify.py` passes `-h string:desktop-entry:board`. The two-key lookup
covers the ordinary case where they merely differ in *case* or where one is
absent; it cannot invent a mapping between two different words.

`SetTextField.liveText` exists for that search field and nothing else: the
component still commits only on Enter/focus-out, because every other user of it
persists a setting and must not see keystrokes.

The harness pins `XDG_CONFIG_HOME` at a synthetic `plasmanotifyrc` with two keys
that are deliberately not installed programs. A test whose expectation depends
on which apps have notified him this week is not a test, and `book` may have no
Plasma config at all.

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

### The first paint of a reload must be SYNCHRONOUS, or the wallpaper flashes

The reload is a handoff of the layer surface, so the compositor keeps showing the
old buffer until the new tree paints — which means the only way the wallpaper can
flash is the new tree committing a frame it has not put the picture in yet. It
did, on every theme and wallpaper change, and the screen went flat `Theme.bg` for
about a tenth of a second. Traced with `Date.now()` warns across one forced
reload:

```
t+0    ms  WallpaperLayer onCompleted   Wall.url.length = 0     <- singleton not loaded yet
t+20   ms  _apply                       len = 79, status = Null <- source assigned AFTER the pass
t+20   ms  Qt.callLater / 0 ms Timer    status = Loading
t+103  ms  status = Ready                                       <- first frame was long gone
```

Two independent causes, and fixing either alone leaves the flash:

- **A singleton completes at the END of the load pass**, so `Wall.url` is empty
  in a consumer's `Component.onCompleted` — the same trap as
  `SettingsStore.loadNow()`, and the same fix: **`Wall.loadNow()` first**, which
  `reload()`s the three `FileView`s and reads `text()` (the `text()` is what
  forces the read to complete).
- **`asynchronous: true` cannot make the first frame.** A 1920x1080 webp decodes
  in 23-37 ms measured with `QImageReader`, and that is a worker thread landing
  after the pass either way. So the first paint of a tree — and ONLY the first
  paint — goes through `WallpaperImage.loadNow()`, which drops `asynchronous`
  for one assignment and restores it on the next line. A cross-fade must stay
  asynchronous: the outgoing frame is still on screen, and the picker previews a
  new wallpaper on every arrow key.

```bash
qs ipc call wallpaper status   # ... firstPaint=ready
```

`firstPaint` is the regression check and it is what the tree recorded at its own
completion, so it stays readable long after the reload. Anything but `ready`
means the flash is back.

### The same rule, for the dock: NOTHING ON SCREEN MAY LOAD ASYNCHRONOUSLY

The wallpaper was not a special case, it was the first instance. Anything the
panel draws that is fetched by a `Loader` or an `Image` has exactly the same
problem, because the reload's first frame is painted from whatever is in the
tree *at completion* and an asynchronous load is by definition not.

`DockTile`'s Loader was `asynchronous: true`, so on every reload all five dock
tiles came up as their 1px frame over `Theme.bg` — a dock of empty outlines,
which is what "the panel flashes black" was. Measured with a `Date.now()` warn
on `Loader.onStatusChanged` across one forced reload, dock mode at 378px:

```
t+0  ms   status = Loading   x5
t+0  ms   Configuration Loaded                          <- the tree is up, it will paint
t+82..95  status = Ready     tasks, clock, calendar, weather, media
```

`asynchronous: false` spends that time inside the load pass instead, where the
old frame is still on screen. **The laziness was notional anyway** — the grid is
ONE PAGE with no scrolling, so every tile in `placements` is on screen at all
times and gets built either way; async only meant *later*, never *not at all*.
The `active` `Binding` in that file is unrelated and must stay: it is about the
property arriving late, not the item.

```bash
qs log | grep "dock tiles"    # nothing = every tile was painted in the first frame
```

`DockGrid._auditFirstPaint()` runs at the grid's own completion and warns **only
on a regression**, naming the tiles that were not `ready`. There is deliberately
no IPC call for it: the answer is only true for the instant it runs, and a poll
from outside always arrives after the tiles have caught up, so it would report a
clean panel whether or not the bug was there.

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
grep -n "kinetic" ~/nix/home/prog/hypr-files/hyprland.lua   # the nix source; rebuild reconciles live
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
NixPath.launch(["filer", dir])                    // a GUI app — see below
NixPath.run(["pkill", "-x", "hyprsunset"])        // a fire-and-forget one-shot
command: ["sh", "-c", NixPath.sh + "exec cava …"] // instead of a bare sh body
```

**Anything that OUTLIVES the click goes through `NixPath.launch`, not `run`.**
`execDetached` detaches the PROCESS — double-fork, reparented to systemd — but
a process cannot leave its CGROUP by running, so every app started from the
runner, the file browser, a notification or a disk tile stayed inside
`quickshell-panel.service` for its whole life. Two bugs, one cause:

- The unit is `KillMode=control-group` with `Restart=always` (both systemd
  defaults), so **any** panel restart SIGTERMs the entire group. The browser and
  every dock-launched app die with the bar.
- Their memory is charged to the panel. Measured on book 2026-08-03:
  `quickshell-panel.service` at **1.79 GB current / 3.36 GB peak** while the
  `qs` process held **176 MB and was flat**. The rest was surfer plus its
  QtWebEngine renderers. A journal line reading `3.4G memory peak` for the panel
  was the browser, filed under the bar — and it was read as a panel leak until
  the cgroup was split by `memory.stat` instead of trusted.

`launch` wraps the argv in `systemd-run --user --quiet --collect --scope`, which
puts the app in its own `run-p<pid>-i<n>.scope` as a SIBLING under `app.slice`.
**`--scope`, not `--unit`**: a scope runs in the CALLER's context, so
`WAYLAND_DISPLAY` and friends are inherited and need no `--setenv` list — the
`settings` wrapper in `quickshell.nix` pays exactly that price for using a
service instead, and is the older half of this same lesson. If `systemd-run` is
missing the `&&` short-circuits to a plain exec, i.e. the old behaviour: never
fail to start the program he asked for.

Verify a launch site rather than assuming — the process tree lies here, because
the app really is reparented to systemd while still sitting in the panel's group:

```bash
cat /proc/$(pgrep -f apps/surfer/main.py | head -1)/cgroup   # must NOT say quickshell-panel
systemd-cgls --user-unit quickshell-panel.service            # should hold qs, cava, pactl — no apps
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
