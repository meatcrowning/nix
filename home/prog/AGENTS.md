# AGENTS.md — the compositor side of the desktop

Hyprland's config (`hypr-files/hyprland.lua`), the `hyprvtb` plugin
(`hyprvtb/`, C++ — compositor-side window titlebars, session save/restore,
kinetic scrolling), and the off-screen sandbox agents must test GUI changes on.

The Quickshell panel has its own guide: `quickshell-files/AGENTS.md`.
Repo-wide rules (rebuild, git, boundaries): `~/nix/AGENTS.md`.
Bumping the compositor pin or the ABI seam: `hyprvtb/PORTING.md` — read that
one **before** touching the plugin or the pin.

---

## `hyprland.lua` is seed-once — edit BOTH copies

It is installed only if absent, because `cursor-recolor.sh` rewrites it in place
at runtime. A fix applied to the nix source does nothing until it is also put in
the live file — the running system keeps the old behaviour indefinitely — and
the reverse, a live-only edit, is silently lost on the next fresh install.
**Editing only one side is the single most common way a change here appears to
do nothing.** It has bitten repeatedly: a stale `focus workspace 50` line lived
on in the live file long after it was removed from source, scattering windows
across two workspaces; a later episode shipped a dead `SettingsStore` binding.

```bash
~/nix/tools/seed-drift.sh          # BEFORE you start — see what is already stale
# …edit home/prog/hypr-files/hyprland.lua AND ~/.config/hypr/hyprland.lua,
#    with targeted string edits — never a wholesale overwrite (it holds the live
#    wal palette and border colours)
~/nix/tools/seed-drift.sh          # AFTER — prove both copies moved. exit 1 = drift
hyprctl reload                     # re-runs the live Lua, re-registers hl.bind, no session disturbance
```

Adding a new seed-once file means adding it to the `PAIRS` list in that script.
Never trust a written claim about current drift state — run the script.

---

## Plugin actions are Lua functions, never dispatchers

`addDispatcherV2` is useless under the Lua config: `hyprctl dispatch X`
*evaluates X as a Lua expression* and then wants a dispatcher object back, so a
plugin dispatcher name resolves to an undefined global and silently does
nothing. The old `hyprctl dispatch hyprvtbsaveclose` in `session-exit.sh` was a
no-op for its entire life — logout saved nothing and closed nothing gracefully
(fixed in v2.54).

Register with `HyprlandAPI::addLuaFunction`; call it as
`hl.plugin.hyprvtb.<fn>()` from a keybind, and:

```bash
hyprctl eval "hl.plugin.hyprvtb.<fn>()"
```

from a script. **`hyprctl eval` returns NO values** — a successful chunk prints
`ok`, and only `error("x")` messages carry text. Any value-returning Lua
function must therefore publish to a state file instead: the kinetic module
writes `~/.local/state/hyprvtb/kinetic-{dump.json,stats.txt,get.txt}`
atomically with a `seq` freshness token. Those paths are `$HOME`-relative, so a
nested harness instance (`HOME=$RUN/home`) is isolated for free. Follow that
pattern.

Also note `hyprctl keyword` refuses outright here ("keyword can't work with
non-legacy parsers") — use `hyprctl eval`. And dispatchers are `hl.dsp.*`
objects passed to `hyprctl dispatch`; a bare dispatcher name is a nil global.

---

## Graceful session exit — close-only, never a snapshot

The panel's power menu (`quickshell-files/PowerMenu.qml`) runs
`quickshell-files/scripts/session-exit.sh` *before*
the power command for any `endSession` item. That script runs
`hyprctl eval "hl.plugin.hyprvtb.close_all()"`, which sends a graceful
`sendClose()` to every decorated non-scratch window — i.e. "clicks the [x]" —
then waits (bounded ~4 s) for them to actually close before returning and
letting the power action fire.

**That is its only job.** Each app gets to save its own state, and the plugin's
`window.close` handler records the window's geometry, which is what makes the
app reopen where you left it. It deliberately does **not** snapshot a session:
logging in must not spawn anything. `sleep` is not an `endSession` item —
windows stay across suspend.

Session *snapshots* (`~/.local/state/hyprvtb/session.tsv`, relaunched by
`vtbRestoreSession` at the next fresh login) are a separate, deliberate act:
`hl.plugin.hyprvtb.save_session()` on Meta+Ctrl+S. **Never call it from a
script** — an unexpected snapshot means the next login spawns a pile of windows,
and restored windows skip the open-reveal animation by design.

---

## `hyprvtb` — where to edit

Hyprland comes from a **pinned** flake input (`hyprland.url =
github:hyprwm/Hyprland/vX.Y.Z`) and the plugin is built against that exact
package. Bumping it is a deliberate act with a ritual: `hyprvtb/PORTING.md`.

Two containment rules the nix `checkPhase` enforces:

- Volatile Hyprland internals may be named **only** in `vtbCompat.hpp`;
  everything else calls `Hl::…`.
- A weak ref to a decoration must be a `CDecoRef`, never a raw
  `WP<CVtbDeco>` — a `lock()` over a unique-owned deco aborts the compositor.

There is also a **temporary** third pin, `hyprland-air` (v0.55.4): book runs
Fedora Asahi's rpm compositor (nix hyprland crashes on Asahi — no GBM), and its
hyprvtb must be built against that exact version. So `vtbCompat.hpp` is
dual-version (`#if VTB_HL_056`) and **seam changes must compile against BOTH
pins.** Delete the bridge when Fedora ships 0.56 — runbook:
`docs/book-hyprvtb-version-bridge.md`.

`hyprvtb/` is the plugin derivation's `src` (`src = ./.`), so any file added or
changed there rebuilds the plugin. That is why this guide lives one level up.

---

## Reloading the plugin after a source edit

**`rbsys` then `hyprctl reload`. That is the whole procedure. No relog, and
never `hyprctl plugin load` / `unload`.**

```bash
# bump the version string in hyprvtb/main.cpp first — one bump per change
git add -N <any new file>          # flake eval ignores untracked files
sudo rebuild-top
hyprctl reload
hyprctl plugin list                # must show the NEW Version, and exactly ONE hyprvtb
hyprctl configerrors               # must be empty
```

It briefly re-decorates every window; the plugin does session save/restore, so
this is safe.

**Why it works:** `hyprland.lua` passes `hl.plugin.load` the **resolved**
`/nix/store/...` path (via `readlink -f`), not the stable symlink. Hyprland
tracks config-loaded plugins by that literal path *string*, and
`CPluginSystem::updateConfigPlugins` early-returns unless the string list
*changes* between reloads. With the symlink the string was constant forever, so
`hyprctl reload` was a no-op and the stale `.so` stayed mapped — which is what
made everyone reach for manual `plugin load` and, historically, a relog. With
the resolved path, each `rbsys` yields a new string and Hyprland does the swap
itself, in the right order and with the right bookkeeping.

### What makes the swap SURVIVABLE (2.65) — do not regress this

A hot swap `dlclose()`s the old image while the compositor still holds pointers
into it, and Hyprland's own cleanup is not enough:
`HyprlandAPI::removeWindowDecoration` lands in `CWindow::removeWindowDeco`,
which only queues the removal and calls `updateWindowDecos()` — and that
early-returns on `!m_isMapped || isHidden()`. Every hidden window (this plugin
hides rolled-up ones and parks minimized ones off-screen) therefore kept a
`UP<CVtbDeco>` whose vtable was about to be unmapped, and the session SIGSEGV'd
at the next window close, inside `~CWindow` under `CWindow::destroyWindow`. That
is what took the desktop down on 2026-07-25. Three things hold it together now,
all in `PLUGIN_EXIT`/`PLUGIN_INIT`:

- `Hl::detachOurDecos()` erases this plugin's decorations from every window
  itself, uncaching them from the positioner, while its code is still mapped.
- `CVtbDeco::restoreForUnload()` runs first, un-hiding rolled-up windows and
  un-parking minimized ones — states only this instance knows how to leave,
  which the incoming one does not inherit.
- `PLUGIN_INIT` decorates hidden windows too (it used to skip them), so a
  minimized window is not left with no titlebar at all after the swap.

### A swap must also be INVISIBLE, not merely survivable (2.71)

Restoring every window on the way out is required, but it left them restored: a
rolled-up window snapped open on `hyprctl reload` and stayed open. So
`PLUGIN_EXIT` now writes the roll/minimize states to
`~/.local/state/hyprvtb/handoff.tsv` before undoing them, and `PLUGIN_INIT`
re-applies them (`toggleRollup(false)` — no animation) after it has decorated
the existing windows. Keyed by window ADDRESS, which is only meaningful because
a hot swap happens inside one compositor process: the file records that
process's PID, is discarded on a mismatch, and is consumed (deleted) on the
first read either way, so nothing leaks into a fresh login. Note the fix cannot
show on the first reload *from* an older build — the outgoing instance is the
half that has to write the file.

### Test a swap without gambling the session

```bash
hyprvtb/tools/hotswap-test.sh [plugin.so]
```

Rolls a window up in a nested Hyprland, swaps the plugin under it, and checks
who owns the titlebar afterwards. It passes on 2.65 and fails on 2.64, so it is
a real regression test, not a smoke check. Two gotchas it encodes: the swap is
asynchronous (Hyprland's config watcher usually performs it), and an idle nested
compositor will not notice until an IPC request turns its event loop.

### If a swap does kill the compositor

The session no longer falls off a cliff. `sys/dsk/hyprland.nix` replaces the
wayland-session's `start-hyprland` — whose answer to an unclean exit is
`--safe-mode`, i.e. no config at all — with `hypr-supervise`, which records the
plugin build that was live in `~/.local/state/hyprvtb/crashed-with` and restarts
with the REAL config. `hyprland.lua` reads that on the way up and loads the last
**known-good** build instead, leaving the reason in `.../quarantined`. So a bad
plugin costs one version and a breadcrumb, not the desktop. After 3 crashes in a
row the supervisor gives up and hands over to `start-hyprland` — at that point
it is not the plugin's fault.

book has no `hypr-supervise` (it is a Fedora session), so a compositor crash
there is still a relog; its quarantine block only picks the known-good build at
the next start. book **does** hot-swap properly since 2026-07-26 — its live
`hyprland.lua` now carries the resolved-path + quarantine block; it used to load
the symlink, so reload had never swapped there
(`docs/book-hyprvtb-version-bridge.md` records the correction).

### Never go back to manual `hyprctl plugin load` / `unload`

It is the source of every "hot reload is unstable" report:

- `loadPluginInternal` rejects a path that is already loaded, but a *different*
  string for the same `.so` loads a **second instance**. That instance's
  `registerPluginValue` calls all fail with `name collision: already
  registered`, so it owns no config keys.
- Unloading either instance runs `onPluginUnload`, which erases the
  `plugin:hyprvtb:col.*` keys from `m_configValues` outright. Now nobody owns
  them, the next parse of `hyprland.lua` throws `unknown config key`, the Error
  Overlay trips and titlebars lose their colours. **`hyprctl reload` cannot fix
  this** — only a plugin *load* re-registers keys, and the Lua config manager has
  no `m_failedPluginConfigValues` grace list like the legacy one.
- Unload matches by exact path string and `plugin list -j` does not print paths,
  so a stale instance can become unreachable (its store path may even be
  garbage-collected) — at which point a relog really is the only way out.

---

## Kinetic momentum scrolling (`vtbKinetic`, ≥2.78)

The plugin SYNTHESIZES input. macOS-style momentum, generated compositor-side:
the module watches finger-source axis events on the bus and, at the finger-lift
stop, keeps emitting decaying axis events **at the seat** (`Hl::sendAxis` →
`CSeatManager::sendPointerAxis`), which is *downstream* of the
`input.mouse.axis` bus — so synthetic events can never re-enter the plugin's own
listeners, decos or keybinds. **Do not "fix" that by routing through
`CInputManager::onMouseWheel`** (it re-enters the bus and defers a frame the
timer cannot supply). Full spec and provenance: `docs/kinetic-scroll.md` and
`docs/kinetic-scroll-research/`.

- **A 0-value `sendPointerAxis` IS the protocol `axis_stop`** — never emit a
  literal 0 mid-flight (the wire cousin of the degenerate-rect abort). The seam
  wrapper refuses zeros and non-finite values.
- **The terminal stop is withheld ≥300 ms**, which zeroes every client-side
  fling estimator (Chromium 200 ms, GTK/kitty 150, Firefox 100). That one rule
  is why there is no double momentum.
- **Any timer added to this plugin must be disarmed in `PLUGIN_EXIT` before
  anything else**, and any OPEN axis sequence closed with a 0-delta send plus a
  frame — a client left mid-sequence believes scroll is in progress forever.
- Ships **default off**. Enable and tune live:

  ```bash
  hyprctl eval "hl.plugin.hyprvtb.kinetic_set(true)"            # instant off: kinetic_set(false)
  hyprctl eval "hl.plugin.hyprvtb.kinetic_set(\"friction\", 3.6)"  # 2.6..7.0, default 3.6 (mac-anchored)
  ```

  **`hyprctl reload` clears the runtime override**, so every plugin hot-swap
  disables momentum until it is re-enabled — or until the
  `plugin:hyprvtb:kinetic` config key is promoted into both `hyprland.lua`
  copies. That is a deliberate trial-mode property, not a bug.
- **Testing:** `kinetic_test(dy, n, ms)` injects through the real estimator,
  DRY by default (trace-only, safe in the live session). A wet run is refused
  without a prior `kinetic_set("unsafe_wet", 1)` and must only ever happen in a
  nested compositor — `sendPointerAxis` targets the seat's pointer focus, so the
  sandbox monitor cannot isolate it. The battery: `hyprvtb/tools/kinetic-test.sh`
  (nested, dry+wet numeric acceptance), `hotswap-test.sh` (mid-flight swap),
  `nested-smoke.sh` (crash-class). Run frame-starved nested (sandbox on book)
  with `VTBSMOKE_EXPECT_FRAMES=0` — nested compositors never step render-driven
  animations there; an environment artifact, not a regression.

---

## Testing GUI changes: `tools/sandbox.sh`, never the user's screen

```bash
~/nix/tools/sandbox.sh start
~/nix/tools/sandbox.sh exec <cmd>
~/nix/tools/sandbox.sh shot [file]     # grim of that monitor
~/nix/tools/sandbox.sh clients
~/nix/tools/sandbox.sh stop
```

It creates a virtual monitor in the live session (`hyprctl output create
headless`) and launches windows onto it: a real monitor to the compositor —
workspaces, decorations, animations, every frame rendered — that no cable leads
to, so nothing appears in front of the user.

- `exec` restores keyboard focus to the user's monitor afterwards (a new window
  takes focus even with `silent`).
- `stop` closes the sandbox's windows BEFORE removing the output — Hyprland
  migrates a removed monitor's windows onto a real one — then prunes the classes
  it launched from the plugin's per-class geometry memory.
- Windows there are decorated by the **live** plugin instance, which is the point
  (you test what is actually running) — but it is therefore **no protection
  against a plugin crash.** For an unswitched plugin build use the nested
  harness `hyprvtb/tools/nested-smoke.sh`, which is properly isolated but
  appears as a window.
- Three headless-parent designs were tried and rejected first; `tools/sandbox.sh`'s
  header records why, so they do not get retried.

Verification is by IPC and logs, never by looking: `hyprctl plugin list`,
`clients`, `workspaces`, `layers`, `configerrors`, and the Hyprland log. The
user does all visual and interaction checks.
