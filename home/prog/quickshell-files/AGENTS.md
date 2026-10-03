# AGENTS.md — Quickshell panel

QML for the Hyprland bar, widgets, wallpaper, and popups. This directory does
not identify the user's active desktop. Follow the [root guide](../../../AGENTS.md)
for host/session detection, ownership, commits, rebuilds, and test isolation.
Read [the compositor guide](../AGENTS.md) for compositor changes and
[DESIGN.md](../../../docs/DESIGN.md) for visual changes. Leave an inactive panel
stopped under Plasma, Labwc, or another desktop.

## Task routing

Read the relevant reference before changing its subsystem. These describe
current contracts; incident narratives and superseded measurements stay in Git.

| Area | Reference |
|---|---|
| Notch, runner, edge drag, frame geometry, filter focus | [Geometry and input](../../../docs/agents/quickshell-geometry.md) |
| Task manager, hardware readings, remote top, media, text | [Widget contracts](../../../docs/agents/quickshell-widgets.md) |
| Notification admission, lifetime, sender identity, isolated tests | [Notifications](../../../docs/agents/quickshell-notifications.md) |
| Resource investigation | [Resource runbook](../../../docs/agents/resource-quickshell.md) |

## Getting an edit live

Edit Nix sources and follow the root commit/rebuild workflow for the measured
host. Most installed QML files are store symlinks. Quickshell watches the
resolved path, so a symlink swap needs a forced reload through writable
`Theme.qml`: temporarily append a comment, then restore the original content
in place. Preserve its inode; `sed -i`/`mv` will not trigger the watcher, and
identical content is deduplicated. Do this only for an active Hyprland panel.
Never run bare `qs`, which starts another panel.

Activation reconciles `Theme.qml` in place, retaining the runtime wal palette.
Durable edits belong in source, not the live file. Run `tools/seed-drift.sh`.
Parse failures preserve the previous QML tree; inspect the new portion of
`qs log` and the final `Configuration Loaded`. A multi-file activation can
briefly expose mixed old/new types, so tolerate absent optional properties.

## Verification

Use logs, read-only IPC, `qmllint` with the correct import paths, and isolated
harnesses. The user performs live visual/interaction checks. Do not launch
live test windows, drive focus or pointer, capture the live screen, or send
live notifications. Only query IPC when the target panel is active.

```bash
qs ipc show
qs ipc call view geom
qs ipc call view trace
qs ipc call state carried
qs ipc call live all
qs ipc call live tiles
qs ipc call launcher geom
qs ipc call launcher query gimp
qs ipc call wallpaper status
hyprctl layers
```

`qs log` is cumulative: capture its line count before a change and inspect the
new tail. `view trace` contains the last user-performed drag; do not generate
one on the live desktop. `hyprctl layers` checks namespace, level, and size.
Do not call mutation IPC merely because it is listed beside diagnostics.

Offscreen fixtures need scratch `HOME`/XDG paths as well as
`QT_QPA_PLATFORM=offscreen`, or `SettingsStore` can write live settings. Source
`tools/lib/session-guard.sh` and immediately use the matching guard. Stub
external data/process singletons, and include generated `Host.qml`,
`Location.qml`, and other required imports. Use a private DBus session where
needed; teardown belongs in a trap. Isolation failure is fatal.

`MultiEffect` has no shader path offscreen. Rendering tests that depend on it
need the guarded headless sandbox, never the user's output. A scratch HOME
also loses the installed font unless the fixture supplies it; do not mistake
fallback-font dimensions for production measurements.

## Reload and first-paint state

`shell.qml` carries pins in `$XDG_RUNTIME_DIR/qs-live-pins` and widget data in
`PersistentProperties`. Pins load synchronously through `FileView.blockLoading`
and `snapPinned()`. The v2 PID distinguishes an in-process reload from a new
process; an absent runtime file identifies a new login.

`PersistentProperties` must be a direct child of the root `Scope`. Transfer
strings, not JS objects/arrays, between QML engines. Sources expose
`stateJson()`, `restoreState()`, and `stateRev`; high-rate VU/spectrum sources
snapshot every 250 ms. Restore before the first frame. `state carried` reports
carried sizes and live buffer lengths; histories should continue across reload.

`SlidePopup` skips its layer remap on in-process reload because Quickshell
hands over the mapped surface. Other paths, including pre-map, must remap:
layer selection is latched at construction. Widget layers should remain bottom
(level 1), with no widget close/open-layer events during reload. Notifications
may close/reopen because `NotificationServer.keepOnReload` is false.

Gate persisted-geometry Behaviors on `ViewMode.settling` (the first 400 ms),
including bar width, layout crossfades, wallpaper visible area, and dock tiles.
Seed `applyReserve()` from the settle timer, not `Component.onCompleted`, or
restoring a panel can displace windows as if it had grown. `view geom` should
eventually report `settling=false`.

One-shot handlers must call `SettingsStore.loadNow()` before branching on
settings. `FileView.reload()` followed by `text()` forces the synchronous read;
`reload()` alone does not ensure adapter values are ready.

Never push values from the per-reload tree into a singleton: an outgoing
binding can overwrite the incoming tree's state during teardown. Derive shared
metrics in singletons and expose readonly pulls, as `NotchModel` does.

## Surfaces, size, and motion

`PanelWindow.visible` maps/unmaps a surface; unmapped geometry can be zero.
Never derive visibility from that geometry. Keep an imperative open flag until
the closing slide finishes, as `SlidePopup._visSurface` does.

A zero-sized `PopupWindow` disconnects the entire panel. Measure named children
or entries independently of the popup's own size, apply positive floors, and
refuse degenerate geometry. Measure an entry's own `shown` flag, not effective
`Item.visible` while its parent is closed. Test two open/close cycles in an
isolated fixture. A protocol failure may appear only in `journalctl -t xsession`;
correlate its PID with Quickshell's runtime directory.

All slides use `ViewMode.slideMs` and `ViewMode.slideEasing`; every animation
duration goes through `ViewMode.ms()` for reduce-motion, speed, and debug scale.
Timing comes from hyprvtb's `motion.json`; its fallback must match the plugin
default. An animation-guard timer uses `ViewMode.ms(ViewMode.slideMs) + 20`,
with the frame margin outside scaling. Crossfades, hover feedback, VU follow,
and gesture snaps have their own durations, still passed through `ms()`.

Moving edges belong in Items inside constant-sized layer surfaces. Surface
resizes require configure/ack roundtrips and cannot track a pointer accurately.
Never animate or quantize a live resize, or update `exclusiveZone` per pointer
event. Apply quantization/reservation at commit; discrete entry/collapse snaps
may animate. Wallpaper follows committed `barWidth`, not every pointer event.

`Tooltip` callers set `show`, never `visible`; it owns delayed opening and the
closing slide. Its full-size surface contains the animated clip. New tooltip
surfaces should respect `TooltipState.frozen` during user-initiated capture.

## View mode and grid contracts

Use `ViewMode.barHorizontal` / `barAtStart` for edge orientation. Dock mode and
the shortcut notch are vertical-only: central predicates make downstream
consumers see the ordinary no-dock/no-notch state on horizontal edges.
Classic horizontal layout is a separate host sharing the same widget types,
not a rotated vertical layout. Grid positioners own both child axes.

The edge grip switches classic/dock modes. Entry is a threshold gesture with
one destination (`dockPx`), not continuous stretching. Resizing tracks the
pointer only after entering dock. Keep `exitFrac < minFrac`, so the narrowest
legal dock remains stable. Architecture/gesture changes require root-guide
approval; do not add a runner button or a second entry mechanism casually.

`liveWidth` is rendered width; `barWidth` is committed/persisted width.
`Theme.barWidth` is only classic width. Both layouts exist and crossfade via
`showDock`; hidden layouts must set `visible: false` to disable hover zones.
Dock retires desktop widgets and restores the previous pins on return. Its
startup path must not re-pin widgets from either reload state or login defaults.

`DockGrid` is a single page with no scrolling. Row height derives from panel
height; column/row counts do not change with panel width. New widgets must
fit by reallocating rows. Keep `placements` a stable Repeater model; runtime
changes use delegate deltas (`qRow`, `qSpan`) rather than recreating every tile.

`DockTile` Loaders are synchronous for first paint; preserve the separate
`active` Binding for late properties. `_auditFirstPaint` catches unready tiles
at completion; a later IPC poll cannot prove the first frame was ready.

Tile reports carry generations and refuse non-positive geometry. New generations
clear the table; old reports are ignored. Delegates re-report on generation
change. Virtual screens use generation -1 and never populate measurements.
`live tiles` describes the newest physical grid, which may be a different
monitor; `wants` is natural height, not a minimum. Do not infer lingering QML
trees from a cumulative log containing many sequential generation IDs.

## Widgets and persistent preferences

Data belongs in a singleton, drawing in `*Content.qml`, placement in
`SlidePopup`/`DockTile`. Popup and dock copies coexist. Content `active` defaults
to false and gates every expensive timer/process/repaint. Popups pass `open`,
not `visible` (layer remaps can briefly unmap them); dock hosts pass layout
visibility. Consumers use idempotent `watch(obj, on)` sets, not counters.

Per-monitor widgets must not own duplicate processes. The VU's cava belongs in
`SysInfo`; spectrum and VU are gated by `SysInfo.audioActive`. Exclude permanent
EasyEffects output streams when detecting activity. Crash-retry lifecycle code
restores `Qt.binding`, not a bare assignment that severs the gate. Stopping
zeroes levels. The intended process count is two while needed and none when
idle, independent of monitor count.

Content stretches into its host. Keep natural implicit sizes independent of
actual width/height to avoid feedback loops. `MetricChart` shares CPU/GPU/net
rendering; series changes trigger repaint. Its range property is `axisMax`,
not `scale`, which belongs to `QQuickItem`.

User choices belong in `SettingsStore`, followed by `SettingsStore.save()`;
otherwise the polling reader reverts them. `PersistentProperties` survives
reload only, not logout. Local transient state stays local. Desktop-wide app
appearance settings also use this file through `apps/pylib/deskstyle.py`.

Volume is a mirror of WirePlumber's default sink, not a stored panel setting.
Do not restore volume from `settings.json`. Brightness uses machine-local
`gammaLevel` / `brightnessHw`; `-1` leaves untouched hardware alone. Restore
before the first poll only for a new process, never after carried-state restore.
Call `SettingsStore.loadNow()` first. Read-only audio diagnosis starts with
`wpctl get-volume @DEFAULT_AUDIO_SINK@`; meters describe upstream audio, not
proof the hardware sink is audible. See [volume persistence](../../../docs/volume-persistence.md).

## Windows, icons, and text

Every toplevel consumer calls `WinState.offOutput(appId, title)`; the foreign
protocol lacks monitor identity. Task cells, media player detection, and askpass
must all ignore virtual-output clients. Hardware identity decides physical
outputs; a headless name corroborates but cannot hide real hardware. Ambiguous
class+title joins fail visible. `screenIsVirtual()` is synchronous for first
paint. A sandbox tag identifies ownership; it does not replace visibility.

Use `AppIcon.qml` everywhere. Tint only bespoke seals; foreign icons retain
their authored details. Declare new seals via `my.appSeals` beside the app's
module; `AppSeals.qml` is generated. Oxygen recolouring and Vivaldi titlebar
integration are owned outside the panel; see the compositor guide.

Use `Glyphs.px()` for external display text, preferably at ingest. Never map
identifiers, paths, commands, raw window-title join keys, or editable values
that will be written back (rename and filesystem labels). Unsupported scripts
remain intact rather than becoming question marks.

Check hardcoded glyphs against the actual font's glyph indices. Native elision
already substitutes ASCII dots when needed. An eliding Text must not compute
its width from its own `implicitWidth`; use independent `TextMetrics`.
Use one mirrored `v` with an integer origin for up/down affordances; `^` has
different font metrics. Detailed clock/text contracts are in the widget reference.

## Scrolling and process launches

New scroll areas use `KineticListView`, `KineticGridView`, or
`KineticFlickable`, never bare scrolling types. `Kinetic.qml` owns panel scroll
physics; per-instance overrides need a reason. Discrete wheel controls use
`WheelNotch.steps(wheel)`, never an event-sign test. Layer surfaces are excluded
from compositor coasting, so panel Qt-side kinetics remain necessary. Retuning
friction must keep the Hyprland config, this singleton, and `apps/qmlcommon`
aligned; do not depend on runtime compositor overrides surviving reload.

Use `NixPath` for launches on both hosts: Fedora's session PATH on book may
omit Nix profiles. Its shell prefix appends profile paths while preserving
distro precedence. Add binaries to `NixPath.launchTargets`; unresolved targets
warn at startup. Check installation as well as PATH when a command is missing.

```qml
NixPath.launch(["filer", dir])                    // long-lived app
NixPath.run(["pkill", "-x", "hyprsunset"])        // one-shot
command: ["sh", "-c", NixPath.sh + "exec cava …"] // Process shell body
```

Anything outliving a click uses `launch`: `execDetached` does not leave the
panel's cgroup. `launch` creates a sibling systemd scope with caller session
environment. Inspect `/proc/<pid>/cgroup` to verify separation. Do not hardcode
`~/.nix-profile/bin`; top uses the system/Home Manager profile paths.

## Wallpaper and private defaults

`Wall` selects path/mode; `WallpaperLayer` owns Background surfaces;
`WallpaperImage` owns crossfade frames. `wal-set.sh` publishes `current` and
`current.mode` in place so watches keep their inodes. `--wallpaper-only` changes
selection without applying palette or reloading Theme.

Bind image `sourceSize` to monitor resolution for scale or natural size for
tile, never animated width. Keep the prepared blurred backdrop static during
drags. `Wall.loadNow()` reads synchronously at completion; `WallpaperImage`
decodes its first frame synchronously, then resumes async crossfades.
`wallpaper status` should report `front=ready` and `firstPaint=ready`.

`quickshell.nix` generates `Location.qml` from the private flake input. It only
supplies first-run/reset weather defaults; persisted settings win. Keep
locations and coordinates out of public source and comments.
