# AGENTS.md — the compositor side of the desktop

Hyprland's config (`hypr-files/hyprland.lua`), the `hyprvtb` plugin
(`hyprvtb/`, C++ — compositor-side window titlebars, session save/restore,
kinetic scrolling), and the off-screen sandbox agents must test GUI changes on.

The Quickshell panel has its own guide: `quickshell-files/AGENTS.md`.
Repo-wide rules (rebuild, git, boundaries): `~/nix/AGENTS.md`.
Bumping the compositor pin or the ABI seam: `hyprvtb/PORTING.md` — read that
one **before** touching the plugin or the pin.

**Anything the plugin DRAWS — titlebar cells, labels, tooltips, shadows, the
roll/open/close animations — is governed by `~/nix/DESIGN.md`**, the desktop's
design language. The plugin is one of four codebases that put pixels on this
screen and the user cannot tell them apart, so its glyph vocabulary, its
timings and its colours are shared with the panel and the apps, not local
choices. The window roll in/out is the **reference** every other sliding
animation on the desktop is matched to.

**That reference is a config key, and this plugin OWNS it** (≥2.90).
`plugin:hyprvtb:slide_duration_ms` (260) and `plugin:hyprvtb:roll_slide_frac`
(0.55) are the roll's two beats — and therefore also the panel's popups, the
titlebar tooltip and the six apps' drawers. They were `static constexpr` until
2.89, which meant the other codebases hand-copied 260 out of a C++ comment, and
the panel spent its life at 220 as a result. `vtbPublishMotion()` (main.cpp)
writes the resolved values to `~/.local/state/hyprvtb/motion.json` (the panel
reads it with a watching `FileView`) and to a generated
`~/.local/state/hyprvtb/DeskMotion.qml` (the apps read it with a `Loader` —
plain Qt QML has no file reader and `XMLHttpRequest` refuses `file://` without
a blanket permission flag). It runs on every `config.reloaded`, so **retuning
the whole desktop's motion is one number here plus `hyprctl reload`**, with
nothing restarted. Read them through `Cfg::slideDurationMs()` /
`Cfg::rollSlideFrac()`, never cached in a member: those accessors clamp, and a
0ms duration is a division by zero in the roll's progress step whose NaN lands
in an animated `CBox` — the degenerate rect `renderRect` aborts on.

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

**Empty inner column? Dump the app-button server before touching the plugin:**

```bash
hyprctl eval "hl.plugin.hyprvtb.ipc_dump()"      # -> ~/.local/state/hyprvtb/ipc-dump.json
```

It separates the three causes that all look identical on screen: `"named":
false` (the socket lost its filesystem name — the listener is alive but
unreachable, see 2.85 and 2.92), no entry in `regs` for the window's pid (the app never
connected, or connected under a different pid than `getPID()` reports for its
window), or a `regs` entry that IS there, which moves the hunt to rendering.

**`"named": false` is now self-correcting, and that is load-bearing.** The name
only ever changes hands by `rename()` (bind a temp path, rename it into place),
and the I/O thread re-takes the name within a second if the path stops naming
its inode — because a nameless listener is invisible: every app already
connected keeps its inner column while every app launched afterwards gets
`ENOENT` from `connect()` and can never recover. It read to the user as "the
inner titlebar buttons of windows are no longer visible" and to an agent as an
app-startup bug, since the apps genuinely were not registering. **Diagnose it
from outside the plugin before suspecting `apps/`:** a bare
`python3 -c "…VtbClient()…"` that cannot connect proves the socket, not the app.
Do not replace either half with an `unlink()`; both causes (2.92) were an
unlink with a gap after it.

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
and restored windows skip the open-reveal animation by design. To find out what
a snapshot *would* contain, use `session_probe()` (below): it runs the same
selection into a scratch file and arms nothing. Neither side of the snapshot
carries an agent's sandbox windows since 2.93 — also below.

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
`docs/agents/kinetic-scroll-research/`.

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

  **`hyprctl reload` CLEARS the runtime override.** `kinetic_set(true)` is a
  trial mode, not a setting: never rely on it for anything that must survive a
  reload, a plugin hot-swap or a relogin. Momentum is on for real on air/book
  only because the `plugin:hyprvtb:kinetic` **config key** is set in both
  `hyprland.lua` copies (from `host.kinetic`); use the key, not the setter.
- **Testing:** `kinetic_test(dy, n, ms)` injects through the real estimator,
  DRY by default (trace-only, safe in the live session). A wet run is refused
  without a prior `kinetic_set("unsafe_wet", 1)` and must only ever happen in a
  nested compositor — `sendPointerAxis` targets the seat's pointer focus, so the
  sandbox monitor cannot isolate it. The battery: `hyprvtb/tools/kinetic-test.sh`
  (nested, dry+wet numeric acceptance), `hotswap-test.sh` (mid-flight swap),
  `nested-smoke.sh` (crash-class). Run frame-starved nested (sandbox on book)
  with `VTBSMOKE_EXPECT_FRAMES=0` — nested compositors never step render-driven
  animations there; an environment artifact, not a regression.

### Every new scroll surface must honour the kinetic config

**Any scrollable view added anywhere in this desktop — panel, app, script —
MUST take the compositor's momentum as-is.** Momentum arrives as ordinary
high-resolution finger-source axis events, so "honouring it" is three
obligations on the receiving code:

1. **Delta-proportional, never sign-only and never notch-quantised.** A handler
   that reads only the sign, or rounds to a detent, turns a 60 Hz coast into
   dozens of full-size steps. This is what put `viewer` on the deny list
   originally (sign-only zoom, 12 events saturated 1..8) and what keeps `mpv`
   on it now (`add volume ±2` per wheel event).
2. **No toolkit-side momentum stacked on top.** One decay curve, generated
   compositor-side. Do not add a flick/fling/deceleration animation to a view
   that already receives synthetic axis events.
3. **Handle the sub-pixel/detent discriminator.** Distinguish a
   high-resolution pixel delta from a mouse detent and scale each
   appropriately, or a wheel notch moves one pixel while a coast moves pages.

**The single source of truth for the feel is the `plugin:hyprvtb:kinetic*`
keys in `hypr-files/hyprland.lua` (BOTH copies — seed-once), with the per-host
`kinetic` flag generated into `host.lua` by `hypr-host.nix`.** Tune there, never
with a per-file literal, and never by re-deriving the physics client-side.

**Known non-participants — do not re-chase these:**

- **XWayland clients** (`kinetic_deny_xwayland = true`): the axis →
  core-button-4/5 conversion inside Xwayland was never observed, and a leaked
  tail in a core-button client is a long click train. `feh`, `vlc` and wine/SDL
  are XWayland on book (verified via `hyprctl clients -j`); Firefox, Chromium,
  qutebrowser, GTK3/4 and every Qt app here are native Wayland and do get
  momentum.
- **Clients that own their own fling** (Chromium 200 ms, GTK/kitty 150,
  Firefox 100) are neutralised by the ≥300 ms withheld stop, not by config.
  kitty additionally ships `momentum_scroll 0.96` (Wayland, finger devices):
  end-gated, so the withhold zeroes it; `momentum_scroll 0` in
  `kitty-files/kitty.conf` is the documented kill switch if doubling is ever
  *felt* — it has never been measured.
- **kitty's TUI passthrough is line-quantised by the terminal protocol.**
  `pixel_scroll` keeps kitty's own scrollback sub-line, but full-screen TUIs
  receive discrete line events; that cannot be made smooth from this side.
- **`top` gets none of this** — `host.kinetic = false` there, no finger source.

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

**The promise is "nothing of the agent's reaches his screen", and the monitor is
not the only way onto it.** A headless output hides the window's PIXELS. Anything
that enumerates windows without asking which output they are on puts them back in
front of the user — the Wayland foreign-toplevel list carries appId, title and
activated and no monitor at all, so the panel's taskbar showed every agent's test
window in the user's bar for the whole life of the sandbox (found 2026-07-27, by
him). **Before you add anything that walks the window list, ask whether a sandbox
window would appear in it**, and filter on the output:

- **The panel** joins the monitor back on through `WinState.qml`, whose poll
  already reads `hyprctl -j monitors; hyprctl -j clients`. It owns the one
  definition of "physical output" and every consumer asks it
  (`WinState.offOutput(appId, title)`): the taskbar cells, `Media.playerUp`,
  `Askpass.active`. See `quickshell-files/AGENTS.md`.
- **A monitor is physical if the compositor has any hardware identity for it** —
  non-zero physical size, or a make/model/serial/description. A headless output
  has none of those. Do NOT key on the name alone: the user may attach a second
  REAL monitor and its windows must still appear. (`HEADLESS-n` is ORed in as
  corroboration only — it can add virtual outputs, never subtract a real one.)
- **Every sandbox window is also TAGGED `sandbox`** (`[workspace N silent; tag
  +sandbox]` in `exec`), which is the discriminator that survives the window
  being MOVED. `stop` closes by tag as well as by workspace for that reason.
  Use the tag for "whose window is this", the monitor for "can he see it".
- **The session snapshot is filtered on BOTH sides (2.93).** It used to record
  every decorated window regardless of output, so a snapshot taken while a
  sandbox was up would have relaunched an agent's test windows on the user's
  desktop at the next fresh login — the leak surviving a reboot. Now:
  - **save** skips a window on a headless output *or* carrying the `sandbox`
    tag (`vtbAgentWindowReason`). The monitor test asks Aquamarine
    (`Hl::headlessMonitor` → `IOutput::getBackend()->type() ==
    AQ_BACKEND_HEADLESS`, present on both pins) rather than inferring from
    hardware identity the way the panel must — the compositor knows which
    backend made the output. The identity test survives only as the fallback
    for a monitor with no `m_output` to ask. Two tests because each covers the
    other's blind spot: a window the sandbox never launched carries no tag, and
    a sandbox window that got MOVED is on a real monitor.
  - **restore** drops an entry whose saved geometry lands on no visible monitor
    (headless outputs excluded) or is degenerate, because an *older* file can
    still hold sandbox windows. Such an entry was never restorable anyway — the
    restore path places a window at its exact saved position with no clamp.
- **`session_probe()` answers "what would a snapshot do?" without arming one.**
  `save_session()` may never be called from a script, which used to leave its
  selection untestable. This runs the same selection into
  `~/.local/state/hyprvtb/session-probe.tsv` and the same restore filter into
  `session-probe-restore.tsv` (with `# skipped <cls> (reason)` lines), touching
  neither `session.tsv` nor any process. An optional path argument evaluates a
  *fabricated* snapshot's restore verdicts, so the drop rules can be exercised
  against geometry no live window has:

  ```bash
  hyprctl eval "hl.plugin.hyprvtb.session_probe()"
  hyprctl eval "hl.plugin.hyprvtb.session_probe(\"/tmp/fake-session.tsv\")"
  ```

- `exec` restores keyboard focus to the user's monitor afterwards (a new window
  takes focus even with `silent`).
- **`load_state` now refuses to run if the monitor named in `/tmp/vtb-sandbox/
  state` has gone** (another agent's `stop`, a stray `hyprctl output remove`).
  Hyprland moves that workspace onto a REAL monitor when the output disappears,
  so a stale state file turned `exec` into "open a window on the user's screen".
  `stop`/`status` still run, with a warning; `start` re-resolves.
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
