# AGENTS.md — compositor side of the desktop

This guide covers Hyprland (`hypr-files/hyprland.lua`), the `hyprvtb` plugin
(`hyprvtb/`), and the compositor-backed sandbox. The panel has its own guide
at `quickshell-files/AGENTS.md`; repo-wide rebuild, git, safety, and host rules
are in `~/nix/AGENTS.md`. Read `hyprvtb/PORTING.md` before changing the plugin
ABI or either compositor pin.

Anything the plugin draws is governed by `~/nix/docs/DESIGN.md`, including
titlebar cells, labels, tooltips, shadows, animation, glyphs, and colours. The
plugin's roll animation is the desktop reference: the
`plugin:hyprvtb:slide_duration_ms` (260) and
`plugin:hyprvtb:roll_slide_frac` (0.55) keys are published by `vtbPublishMotion()` to
`~/.local/state/hyprvtb/motion.json` and `DeskMotion.qml` for the panel and
apps. Read them through `Cfg::slideDurationMs()` and `Cfg::rollSlideFrac()`;
they clamp invalid values, and a zero duration can produce a NaN geometry.

## Mutable Hyprland source

`hyprland.lua` is runtime-mutable: `wal-set.sh` owns the border and seven
plugin colours, and `cursor-recolor.sh` owns the cursor theme. Edit only
`home/prog/hypr-files/hyprland.lua`; activation reconciles it on every switch,
preserving named runtime values and copying the old live file to
`~/.cache/seed-reconcile/` when needed.

```bash
sudo rebuild-top
hyprctl reload
~/nix/tools/seed-drift.sh
```

When adding a runtime-owned value, add a matching `carry` in
`tools/seed-reconcile.sh` and keep `tools/seed-drift.sh`'s `PAIRS` and
`normalize()` in step. Anchor carries at the key, never a broad value shape
such as `rgba(...)`, or Nix-owned values can be imported from the live file.

Drift before a switch is expected. `seed-drift.sh --pre-switch` describes the
reconciliation; preflight must fail only when the reconciler cannot run (exit
2), not for ordinary drift. `tools/seed-gate-test.sh` covers this distinction.

## Hyprland integration

### Monitor reclaim

When the display link drops, Hyprland destroys and re-adds the output. The
`monitor.added` block in `hyprland.lua` restores windows, but it must:

- decide whether a window needs recovery from the monitor rect plus
  `HOTPLUG_MIN_VISIBLE`; deliberately off-screen/edge placement is valid;
- use the panel width only to choose a destination, never to decide whether a
  window is a victim (the panel layer is wider than the reserved rect).

Keep the `>>> monitor-reclaim >>>` markers and the block free of live-only
dependencies. `tools/monitor-reclaim-test.sh` extracts the real block and
stubs `hl`; it must remain the test instead of using a nested compositor,
which would move windows onto the user's monitor. `hl.on` accepts misspelled
events silently; use Hyprland's `CLuaEventHandler::knownEvents()` names such as
`monitor.added`, `monitor.removed`, `window.*`, `layer.*`, `workspace.*`,
`config.reloaded`, and `hyprland.start`/`shutdown`.

### Plugin Lua API

Plugin actions are Lua functions, not dispatchers. Register with
`HyprlandAPI::addLuaFunction`, call from config as
`hl.plugin.hyprvtb.<fn>()`, and from scripts as:

```bash
hyprctl eval "hl.plugin.hyprvtb.<fn>()"
```

`hyprctl eval` prints only `ok`; return values must be published atomically to
state files. Kinetic uses
`~/.local/state/hyprvtb/kinetic-{dump.json,stats.txt,get.txt}` with a `seq`
freshness token. Those paths are `$HOME`-relative, so nested harnesses isolate
them with `HOME=$RUN/home`. `hyprctl keyword` does not work with the modern
parser; use `eval`. `hl.dsp.*` objects are for `hyprctl dispatch`, not bare
plugin names.

`close_pid(<pid>)` is the app-side animated close path
(`pylib/vtbclient.close_animated()`): address the caller by PID, never the
active window. Accept the focused window only when it belongs to that PID;
otherwise require that PID's sole window and call `error()` on ambiguity. Keep
window searches in their own scope and raise the Lua error after all handles
are destroyed; `luaL_error` longjmps past C++ destructors.

For an empty app-button column, dump the server first:

```bash
hyprctl eval "hl.plugin.hyprvtb.ipc_dump()"
# ~/.local/state/hyprvtb/ipc-dump.json
```

`named: false` means the listener lost its filesystem name, not that apps
failed to register. The I/O thread must retake the name after `rename()`
removes it; never replace that repair with an `unlink()` gap. A missing PID in
`regs` is an app-registration problem; a present entry moves the investigation
to rendering. Rendering must consume `CVtbDeco::m_regSnap` advanced by
`mainThreadTick`, including glyph prewarming; do not read `VtbIpc::get` directly
from render or hit testing. The global serial means only that some registration
changed; compare the fresh registration to the snapshot. See
`docs/hyprvtb-titlebar-flash.md`.

## Session exit and snapshots

`quickshell-files/PowerMenu.qml` runs
`quickshell-files/scripts/session-exit.sh` before every `endSession` action.
That script calls `hl.plugin.hyprvtb.close_all()` through `hyprctl eval`, waits
up to about four seconds for graceful app closes, and then permits poweroff,
reboot, or logout. It is close-only: apps save their own state and the plugin's
`window.close` handler records geometry. Suspend is not an `endSession` item.

`hl.plugin.hyprvtb.save_session()` is a deliberate Meta+Ctrl+S action only.
Never call it from a script: it arms the next-login restore and can spawn a
pile of windows. Use `session_probe()` to inspect the same selection without
arming it:

```bash
hyprctl eval "hl.plugin.hyprvtb.session_probe()"
hyprctl eval "hl.plugin.hyprvtb.session_probe(\"/tmp/fake-session.tsv\")"
```

Since 2.93, save excludes headless-output and `sandbox`-tagged windows, and
restore excludes entries on no visible monitor or with degenerate geometry.
`session_probe()` writes `session-probe.tsv` and
`session-probe-restore.tsv`, with skip reasons, without touching
`session.tsv` or processes; its optional path evaluates a fabricated snapshot's
restore verdicts.

## Plugin source, pins, and reload

Hyprland is pinned and the plugin is built against that exact package. Keep
volatile Hyprland internals in `vtbCompat.hpp`; other code uses `Hl::…`. A
weak decoration reference must be `CDecoRef`, never raw `WP<CVtbDeco>`.

`book` uses Fedora Asahi's compositor (`hyprland-air` v0.56.2; Nix Hyprland
crashes there because of GBM), while `top` uses the main pin. The plugin seam is
dual-version via `#if VTB_HL_056`; compile seam changes against both pins.
Remove the bridge only when Fedora ships 0.56, following
`docs/book-hyprvtb-version-bridge.md`. Because `hyprvtb/` is the derivation's
`src = ./.`, any file change there rebuilds the plugin.

For every plugin source change, bump the version in `hyprvtb/main.cpp`, then:

```bash
git add -N <any new file>
./tools/preflight.sh
sudo rebuild-top
hyprctl reload
hyprctl plugin list       # one hyprvtb, new Version
hyprctl configerrors      # empty
```

The Lua config loads the resolved `/nix/store/...` path (`readlink -f`), so a
new derivation changes the literal path and `hyprctl reload` swaps it. Never
use `hyprctl plugin load` or `unload`: a second path creates an unregistered
duplicate, unload erases `plugin:hyprvtb:*` keys, and reload cannot restore
those keys.

The swap must detach this plugin's decorations while its code is mapped,
restore rolled/minimized state, and decorate hidden windows in the new
instance. `PLUGIN_EXIT` writes `~/.local/state/hyprvtb/handoff.tsv`; the new
instance reapplies it without animation, accepts it only for the same
compositor PID, and consumes it. `hyprvtb/tools/hotswap-test.sh [plugin.so]`
tests this in a nested compositor; the config watcher is asynchronous, so an
IPC request may be needed to wake an idle nested instance.

If a swap crashes, `hypr-supervise` quarantines the live build and restarts
with the real config. `hyprland.lua` loads the last known-good build and leaves
`crashed-with`/`quarantined` breadcrumbs. This is configured for `top` in
`sys/dsk/hyprland.nix` and for `book` through ly in `home/prog/ly.nix` and
`docs/agents/book-supervised-session.md`; after three consecutive crashes it
falls back to `start-hyprland`.

## Kinetic scrolling

`vtbKinetic` emits decaying finger-axis events at the seat via
`Hl::sendAxis` → `CSeatManager::sendPointerAxis`, downstream of the
`input.mouse.axis` bus. Do not route through `CInputManager::onMouseWheel`,
which re-enters the listener and defers a frame. A zero axis value is the wire
`axis_stop`, so the seam rejects zero/non-finite values mid-flight; withhold
the terminal stop for at least 300 ms. Disarm every timer in `PLUGIN_EXIT`
first and close open axis sequences with a zero-delta send plus a frame.

Kinetic is default-off. Runtime trials are:

```bash
hyprctl eval "hl.plugin.hyprvtb.kinetic_set(true)"
hyprctl eval "hl.plugin.hyprvtb.kinetic_set(false)"
hyprctl eval "hl.plugin.hyprvtb.kinetic_set(\"friction\", 3.6)"
```

Reload clears these overrides. Persistent settings belong in the
`plugin:hyprvtb:kinetic*` keys in the Nix-source `hyprland.lua`, generated from
`host.kinetic`: enabled on `book`/`air`, disabled on `top`.

`kinetic_test(dy, n, ms)` is dry/trace-only by default. A wet run requires a
prior `kinetic_set("unsafe_wet", 1)` and a nested compositor because seat
events target pointer focus; the sandbox monitor cannot isolate them. Use
`hyprvtb/tools/kinetic-test.sh`, `hotswap-test.sh`, and `nested-smoke.sh`.
Nested compositors may be frame-starved; `VTBSMOKE_EXPECT_FRAMES=0` is an
environment accommodation, not a regression.

Every new scroll surface must use compositor momentum as-is: apply the full
delta (not sign-only or notch quantisation), add no toolkit fling, and
distinguish pixel deltas from mouse detents. Do not re-derive physics per
client. XWayland clients (`kinetic_deny_xwayland = true`) do not participate;
Chromium, GTK/kitty, and Firefox's own fling is neutralised by the 300 ms stop.
kitty's `momentum_scroll` is an optional kill switch in
`kitty-files/kitty.conf`; full-screen TUI protocol events remain line based.

## Nested testing and the sandbox

Never test on the user's focus, pointer, clipboard, windows, audio, or screen.
Use the headless sandbox or an offscreen client and the guards in
`tools/lib/session-guard.sh`; fail closed rather than inheriting the live
`WAYLAND_DISPLAY` or `HYPRLAND_INSTANCE_SIGNATURE`. The user performs visual
checks; evidence is IPC, logs, and traces. Do not script plugin actions that
focus or move the user's window.

Every Hyprland process, including nested harnesses, imports its compositor
environment into the systemd user manager. Harness cleanup must run
`~/.config/scripts/hypr-session-env.sh --restore`; user units that need
Hyprland use the same wrapper. `tools/preflight.sh` warns about dead manager
state. The sandbox starts no second Hyprland.

The three nested harnesses (`hyprvtb/tools/{nested-smoke,kinetic-test,
hotswap-test}.sh`) intentionally do not source the shared guard. Their
`hc()` must positively identify the run by its unique config path in
`/proc/<pid>/cmdline`, reject an empty signature and the live signature on
every call, and use `tools/sandbox.sh exec`.

The launch chain must `exec` all the way to Hyprland. A shell redirection,
`tee`, wrapper, or timeout that forks the final process breaks the sandbox's
PID-based workspace/tag rule and can put a window on the user's monitor. Each
harness also needs an off-screen watchdog and a trap; stop the sandbox only if
that run created it. `hyprctl -i ""` is not a refusal—it targets the live
compositor—so unresolved instance identity is fatal.

Common commands:

```bash
~/nix/tools/sandbox.sh start
~/nix/tools/sandbox.sh exec <cmd>
~/nix/tools/sandbox.sh clients
~/nix/tools/sandbox.sh stop
```

`exec` verifies the window is on the headless output and aborts otherwise.
It tags windows `sandbox`, restores keyboard focus afterward, and closes
windows before removing the output (removal otherwise migrates them to a
physical monitor), then prunes the classes it launched from plugin geometry
memory. `load_state` refuses a missing `/tmp/vtb-sandbox/state`; `start`
re-resolves it, while `stop` and `status` may still warn. The sandbox's live
plugin instance is useful for normal behavior; use the nested harnesses for an
unswitched plugin build.

When walking windows, use both meanings: `sandbox` identifies an agent
window, while a physical output is one with non-zero physical size or make/model/
serial/description. `HEADLESS-n` corroborates but must never hide a real
monitor.
The panel's single physical-output predicate is in
`quickshell-files/WinState.qml` (`WinState.offOutput(appId, title)`).

Session save/restore applies the same isolation: save skips headless or
`sandbox` windows using Aquamarine's headless backend, and restore drops old
entries on invisible/degenerate geometry. Keep both checks because either
tagging or output identity can be missing. `session_probe()` is the safe test
for both paths.

For pixel-only flags, use the headless harnesses
`tools/vtb-titletext-test.sh` and `tools/vtb-flash-test.sh`, not a real-screen
visual check. They must self-check their probe, use distinct probe files for
each condition, and measure absolute title ink rather than ImageMagick's
summed `AE` difference. `hyprctl dispatch exec` uses the compositor's
environment, so an on/off choice cannot be passed by an agent environment
variable; use separate probe files. Verification remains `hyprctl plugin list`,
clients, workspaces, layers, configerrors, and the Hyprland log.
