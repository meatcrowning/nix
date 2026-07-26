# hyprvtb: living with Hyprland bumps

hyprvtb is a compositor plugin. It uses six `HyprlandAPI::` entries and ~forty
*internal* Hyprland headers — so upstream's "no breaking changes" promise (which
covers the plugin API) buys almost nothing here. Every compositor bump is a
porting job, and the whole desktop's window chrome — plus filer, viewer, player
and surfer, which put all their controls in the titlebar — rides on it.

This file is the standing procedure. Read it before bumping Hyprland.

## The two axes of churn

**Axis A — internals move.** Compile-time, mechanical, always a symbol
relocation (`g_pCompositor->m_windows` → `Desktop::viewState()->windows()`,
`w->m_realPosition` → `w->positionAnimation()`, …). The v2.47 port was ten such
renames spread over ~180 call sites. Containment: `vtbCompat.hpp` is the only
file allowed to name a volatile internal; a bump should break *there* and
nowhere else. A `checkPhase` grep in `default.nix` keeps the seam from eroding.

**Axis B — hyprutils semantics tighten.** Runtime, *not* mechanical, and it
compiles cleanly. v2.48 was this: hyprutils 0.14.0 added an assert forbidding
`CWeakPointer::lock()` over a `CUniquePointer`, Hyprland owns decorations via
`UP`, and the compositor started aborting a few seconds into login (from
`stepRollAnim`'s open-reveal callback on the session-restore path). Containment:
`CDecoRef` (in `vtbDeco.hpp`) is a deco weak-ref type that simply does not offer
`lock()`, so the illegal call cannot be written. Shared-owned refs
(`PHLWINDOWREF`, monitors, keyboards) are unaffected and use `.lock()` normally.

**What the seam covers, and what it deliberately doesn't.** Four `checkPhase`
greps hold the line: no volatile internal outside `vtbCompat.hpp`, no
`#define private` anywhere, no raw `WP<CVtbDeco>`, no
`config.foo->value()` outside the `Cfg::` accessors in `globals.hpp`. Two
surfaces the plan flagged turned out to need no work: all drawing already goes
through `CVtbPassElement` (the `Hl::rect`/`Hl::texture` calls run inside its
`draw()`, enqueued with `Hl::addPass`), and `layerSurfaceAt` genuinely requires
the monitor's raw `m_layerSurfaceLayers` array — the hit-test API takes it as a
parameter, so there is no better call to make. One did: the `#define private
public` InputManager hack is gone, because `hasHeldButtons()` is public and is
literally `return !m_currentlyHeldButtons.empty()`.

**A note on dispatchers (Axis C).** Under this Hyprland's Lua config,
`hyprctl dispatch X` evaluates `X` as a Lua expression, so a plugin dispatcher
name registered with `addDispatcherV2` resolves to an undefined global and does
nothing — silently. Plugin actions are exposed with `HyprlandAPI::addLuaFunction`
and invoked with **`hyprctl eval "hl.plugin.hyprvtb.<fn>()"`**; `addDispatcherV2`
is not used anymore and should not come back.

## The pin

`flake.nix` pins the compositor to an exact upstream tag:

```nix
hyprland.url = "github:hyprwm/Hyprland/v0.56.0";
```

Before this, Hyprland came from `nixpkgs/nixos-unstable`, which meant (1) any
unrelated `nix flake update` could drag the compositor forward and ambush a
working session, and (2) nixpkgs bumps `hyprland` and `hyprutils` on independent
schedules — which is exactly how 0.56 and hyprutils 0.14.0 arrived together as
two unrelated breakages in one evening. The hyprwm flakes `follows`-pin their
own hyprutils / aquamarine / hyprgraphics / hyprlang, so pinning here takes the
tuple upstream actually tested, as a unit.

Consumers of the pin:

- `sys/dsk/hyprland.nix` — `programs.hyprland.package` / `.portalPackage`.
- `home/prog/hyprvtb.nix` — passes the same package to `mkHyprlandPlugin` (via
  `pkgs.hyprlandPlugins.override { hyprland = …; }`, because the plugin set
  builds with *that* hyprland's stdenv). The `air` `GIT_*`-forced-to-unknown
  override still applies; it just wraps the pinned package now.

The input is deliberately **not** `follows`-ed onto our nixpkgs: unmodified
inputs are what make `hyprland.cachix.org` (added to `sys/base.nix`) hit, and
overriding them would reintroduce the version skew the pin exists to remove.

### The second pin: `hyprland-air` (TEMPORARY — the book bridge)

Since 2026-07-26 there is a **second** pin, `hyprland-air`
(`github:hyprwm/Hyprland/v0.55.4`), used ONLY to build `air`/book's plugin.
book's compositor is Fedora Asahi's rpm (nix hyprland crashes there — no
Apple-Silicon GBM in nixpkgs Mesa), Fedora is on 0.55.4 while `top` moved to
0.56.0, and a plugin loads only into the exact version it was built against.
`vtbCompat.hpp` therefore carries `#if VTB_HL_056` branches (version detected
from pkg-config via `CMakeLists.txt`'s `VTB_HL_VERSION`, with `__has_include`
probes as fallback) and must keep compiling against BOTH pins — check both
before landing seam changes. Full runbook, port mapping and runtime caveats:
`docs/book-hyprvtb-version-bridge.md` (private nix-docs repo).

**Bumping either pin now has a second question: does the seam still build
against the *other* one?** And when Fedora Asahi ships 0.56, delete the whole
bridge: the `hyprland-air` input, `hyprvtb.nix`'s `hyprlandAir` branch, and
(optionally, on the next natural port) the `#else` arms in `vtbCompat.hpp`.

## Does the seam actually hold?

Ask it whenever you like, without touching the pin or the running system:

```
./tools/bump-dry-run.sh            # against hyprwm/Hyprland main
./tools/bump-dry-run.sh v0.57.0    # against a tag
```

It builds the plugin against that Hyprland and sorts the answer into three
outcomes: builds clean (the bump is free), errors confined to `vtbCompat.hpp`
(the seam held — port one file), or errors elsewhere (**a seam gap**: wrap
those symbols and add them to the `checkPhase` grep *before* porting; closing
the gap is the more valuable half of the work).

The first run of this, against `main` five days ahead of the pin, found
exactly two breakages — and it is worth knowing what they were, because they
are the two shapes this always takes:

- `CKeybindManager::m_dispatchers` **deleted**. Caught inside the seam, as
  designed. The fix was better than a rename: the plugin was reaching into an
  internal string-keyed map to invoke "mouse" and "pin", and both have typed,
  supported entry points (`Config::Actions::mouse`, `Actions::pinWindow`) that
  exist in 0.56 too. Deleting the access beat wrapping it.
- `Config::CONFIG_LEGACY` **deleted** (Lua is the only config type now). This
  one was in `main.cpp` — outside the seam. That is what a seam gap looks like:
  it went into `vtbCompat.hpp` as `Hl::luaConfig()`, and `Config::mgr()` joined
  the enforced grep.

`Hl::luaConfig()` is also a small lesson in writing the seam so a version holds
both ways: asking `type() == Config::CONFIG_LUA` compiles on 0.56 and on main,
where `!= CONFIG_LEGACY` only compiles on one. Prefer the spelling that names
the member which survives. (A `requires { Config::CONFIG_LEGACY; }` probe does
NOT work — a missing name in a non-dependent scope is a hard error, not a
failed constraint.)

**As of v2.60 the plugin compiles unmodified against both the pinned v0.56.0
and upstream `main`.** That is the whole thesis, demonstrated rather than
asserted: the next bump is a tag edit and a smoke test, not a rewrite.

## Bump ritual

1. Bump the tag in `flake.nix` **on its own** — never alongside other changes.
   `nix flake lock --update-input hyprland`.
2. `nixos-rebuild build --flake ~/nix#top` (no sudo needed). The plugin is a
   hard dependency of the system closure, so an **Axis A** break fails here and
   the current generation stays bootable. Fix it in `vtbCompat.hpp`.
3. `sudo rebuild-top`.
4. `./tools/nested-smoke.sh` — starts a **second, nested Hyprland** (as a
   window on the current session, ~20s) with the newly installed plugin and
   exercises decorate → roll up → roll down → save → close, then checks that
   compositor is still alive and its log has no assert/abort/safe-mode. This is
   the **Axis B** gate: v2.48 compiled fine and only died at runtime, in the
   roll animation's `doLater` callback, so a smoke test that never rolls a
   window would have missed it. It talks only to the nested instance
   (`hyprctl -i`) and never touches the live session. Pass a store path to test
   a build you haven't installed yet.
5. **Log out and back in** — do NOT hot-load. On 0.56 `hyprctl plugin
   unload/load` drops the `plugin:hyprvtb:col.*` values and you get an
   "unknown config key" overlay with no titlebars (see AGENTS.md).
6. Visual checklist (the user does this — see AGENTS.md): titlebars present,
   roll-up/unroll animation, open/close animation, maximize/minimize/pin,
   stacked titles, app-button column, edge resize, alt-tab, session restore.
7. Commit the bump alone.

## Worth exporting

Two upstream asks would delete a category rather than relocate it: a stable
window-geometry accessor on the plugin API (`positionAnimation()` /
`sizeAnimation()` moving out of public members broke every plugin that draws
relative to a window — the single largest churn category here), and a
decoration damage helper. If either lands, delete the corresponding shim.
