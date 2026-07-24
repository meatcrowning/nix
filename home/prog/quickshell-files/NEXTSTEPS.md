# Settings program — remaining wiring

Status: **75 / 96 settings wired** to real behavior. This file tracks the rest.
(Everything wired updates live via the panel's settings poll; see SettingsStore.qml.)

## Doable — each needs a subsystem pass (not just a QML binding)

- **paletteColorCount** — `wal-extract.py` `quantize(colors=16)`. Have the extractor
  read `paletteColorCount` from settings.json (fallback 16). Note: changing it
  regenerates every palette (the wal-prepare guard already invalidates on
  extractor change) and only visibly applies on the next wallpaper apply.
- **netInterface / rootMount / smartSsdOnly** — SysInfo.qml + the helper scripts
  (`scripts/disk-usage.sh`, `scripts/disk-smart.sh`, `scripts/sysinfo.sh`).
  Thread the chosen interface/mount/SMART-filter into the shell commands
  (netInterface "auto" = default-route iface; rootMount = which mount for disk).
- **vuBars / vuSmoothing / vuFramerate** — the external `scripts/cava-vu.conf`
  (bars / noise_reduction / framerate). Regenerate the conf from settings and
  restart the cava process (VuMeter.qml owns it).
- **wallpaperDir / wallpaperFit / wallpaperSort** — WallpaperPicker.qml +
  `scripts/list-wallpapers.sh` (source dir + sort) and wal-prepare's tile/scale
  mode decision (fit).
- **autoLockMin** — idle auto-lock. Add an idle monitor (Quickshell.Wayland
  IdleMonitor, if the type resolves) in Lock.qml → `lock.activate()` after
  `autoLockMin * 60`s; 0 = never.
- **lockOnSuspend** — needs a systemd/logind sleep hook (a `before-sleep` user
  service that calls `qs ipc call lock activate`). Outside Quickshell — add via
  the nix config.
- **soundLogin** — currently plays from Hyprland autostart. Move the login chime
  into the shell's existing login-vs-reload detection (widgetStateProc in
  shell.qml) so it reads `soundLogin`.
- **lidCloseAction** — a Hyprland `bindl` on the lid switch (hypr-files/hyprland.lua),
  driven by the setting (suspend | lock | nothing).
- **defaultWidgets** — shell.qml `_defaultWidgets` is host-branched and only
  matters on a first boot with no saved layout (Meta+Ctrl+S). Low value; wire
  only if we want the settings to seed first-boot pins.

## Needs a redesign, or the feature doesn't exist

- **themeMode / accentOverride / pureBlackBg** — the theme is GENERATED from the
  wallpaper: wal-set.sh overwrites Theme.qml's colour block on every wallpaper
  change. A manual override needs Theme to pick manual-vs-wallpaper at read time
  (rename the wal-written `accent`/`bg` to `_walAccent`/`_walBg` and add an
  override layer that every consumer reads). Invasive but doable.
- **reduceMotion / animSpeed** — animation durations are hardcoded per-widget
  across ~15 files. Needs a shared `Theme.animDuration` (scaled by animSpeed,
  0 when reduceMotion) threaded through every Behavior/NumberAnimation.
- **launcherProviderCalc** — no calculator/eval provider exists in Launcher.qml.
  Would mean building the feature, not toggling one.

## Partial (wired, with a caveat)

- **mediaSpectrumBars** — on-screen bar count follows it, but the actual audio
  resolution is fixed by the external cava-spectrum.conf (also needs regenerating).
- **notifImages / notifActions** — the server now advertises them (apps will
  send), but NotificationCard.qml renders no images / action buttons yet.
- **pointerSpeed** — sets the global Hyprland input.sensitivity, but a per-device
  override in hyprland.lua (the trackball) still wins for that device.
