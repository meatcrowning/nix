{ config, pkgs, lib, host, inputs, ... }:

let
  qmlDir = ./quickshell-files;

  # The panel binary. On `top` it is the pinned Quickshell (same source wm.nix
  # installs — see the `nixpkgs-quickshell` input in flake.nix); on `book` the
  # compositor stack is Fedora's, so `qs` is resolved from PATH there and the
  # nix build is never forced. An absolute path on `top` means the service does
  # not depend on the systemd user manager's PATH being right when it starts.
  qsBin =
    if host == "air"
    then "qs"
    else "${(import inputs.nixpkgs-quickshell {
      inherit (pkgs.stdenv.hostPlatform) system;
    }).quickshell}/bin/qs";

  # `settings` — launcher for the standalone Settings program (Settings.qml).
  # It is its OWN Quickshell instance, run from the same config directory as the
  # panel (so it reuses the Theme/PixelText/SettingsStore singletons and
  # recolours with the wallpaper) but selected by path with `-p`. Kept resident
  # and shown/hidden over IPC so toggling is instant; first invocation starts the
  # daemon (the window shows on launch). `-n` guards against a second instance.
  #   settings           -> toggle (the keybind)
  #   settings show|hide -> explicit (the .desktop entry uses `show`)
  settings = pkgs.writeShellScriptBin "settings" ''
    QML="$HOME/.config/quickshell/Settings.qml"
    ACTION="''${1:-toggle}"
    # Already running? Just show/hide/toggle it over IPC and leave.
    if qs -p "$QML" ipc call settings "$ACTION" >/dev/null 2>&1; then
      exit 0
    fi
    # Not running — start it as an INDEPENDENT transient user service (its own
    # cgroup), NOT a bare `qs -d`. Two things this gets right that a plain daemon
    # didn't:
    #   * The Quickshell runner's DesktopEntry.execute() runs us inside a
    #     transient systemd *scope*; a daemonized child is reaped when that scope
    #     tears down. A `systemd-run` unit lives in its own scope and survives.
    #   * `systemd-run --user` runs the command in the *service manager's*
    #     environment, which may not have a live WAYLAND_DISPLAY — so qs would
    #     start, fail to reach the compositor, and exit (then --collect removes
    #     the unit, leaving nothing). Forward the session vars with --setenv so
    #     it connects regardless of who launched us (runner or keybind).
    # reset-failed frees the unit name if a previous run crashed.
    if command -v systemd-run >/dev/null 2>&1; then
      systemctl --user reset-failed qs-settings.service 2>/dev/null || true
      exec systemd-run --user --quiet --collect --unit=qs-settings \
        --setenv=WAYLAND_DISPLAY --setenv=HYPRLAND_INSTANCE_SIGNATURE \
        --setenv=XDG_RUNTIME_DIR --setenv=XDG_CURRENT_DESKTOP --setenv=PATH \
        -- qs -p "$QML"
    fi
    exec qs -d -n -p "$QML"
  '';
  # Theme.qml gets its "wal palette" block rewritten in place at runtime by
  # wal-set.sh (in place, not via rename — Quickshell's hot-reload watches by
  # inode) so it's excluded here and seeded as a real writable file below,
  # instead of a permanent read-only Nix-store symlink.
  qmlFiles = builtins.attrNames
    (lib.filterAttrs (n: v: v == "regular" && lib.hasSuffix ".qml" n && n != "Theme.qml")
      (builtins.readDir qmlDir));
in
{
  xdg.configFile = (lib.listToAttrs (map
    (name: {
      name = "quickshell/${name}";
      value.source = qmlDir + "/${name}";
    })
    qmlFiles)) // {
    "quickshell/scripts/list-wallpapers.sh" = {
      source = ./quickshell-files/scripts/list-wallpapers.sh;
      executable = true;
    };
    "quickshell/scripts/sysinfo.sh" = {
      source = ./quickshell-files/scripts/sysinfo.sh;
      executable = true;
    };
    # cava config for the panel's stereo VU bars (VuMeter.qml)
    "quickshell/scripts/cava-vu.conf".source = ./quickshell-files/scripts/cava-vu.conf;
    # cava config for the media widget's spectrum analyser (MediaPanel.qml)
    "quickshell/scripts/cava-spectrum.conf".source = ./quickshell-files/scripts/cava-spectrum.conf;
    # disk-hover data providers (DiskPanel.qml)
    "quickshell/scripts/disk-usage.sh" = {
      source = ./quickshell-files/scripts/disk-usage.sh;
      executable = true;
    };
    "quickshell/scripts/disk-smart.sh" = {
      source = ./quickshell-files/scripts/disk-smart.sh;
      executable = true;
    };
    # taskbar right-click "Force Quit": resolves a window's pid via hyprctl and
    # SIGKILLs it (TaskMenu.qml / Taskbar.qml)
    "quickshell/scripts/force-quit.sh" = {
      source = ./quickshell-files/scripts/force-quit.sh;
      executable = true;
    };
    # Dock view mode (ViewMode.qml): shove floating windows out from under the
    # panel when it grows. The exclusive zone only reflows TILED windows, and
    # this desktop is almost entirely floating.
    "quickshell/scripts/push-windows.py" = {
      source = ./quickshell-files/scripts/push-windows.py;
      executable = true;
    };
    # Task manager (TaskManagerContent.qml / Procs.qml): instantaneous per-process
    # CPU from two /proc samples, which is what ps's lifetime-average %cpu can't
    # give.
    "quickshell/scripts/proc-list.py" = {
      source = ./quickshell-files/scripts/proc-list.py;
      executable = true;
    };
    # Image-download completion toasts (NotificationCard.qml): given the
    # ~/Downloads path surfer announced, resolve the file's CURRENT location —
    # sort-downloads files images out of ~/Downloads into ~/Pictures within
    # seconds, so the toast must not hard-open a path that went stale.
    "quickshell/scripts/dl-resolve.py" = {
      source = ./quickshell-files/scripts/dl-resolve.py;
      executable = true;
    };
    # Gate for both cava instances (SysInfo.qml VU, Media.qml spectrum): is any
    # application actually playing? Unconditional, that pair cost ~19.5% of a
    # core with nothing playing — see the script's header and
    # docs/perf-cpu-hotspots.md.
    "quickshell/scripts/audio-active.py" = {
      source = ./quickshell-files/scripts/audio-active.py;
      executable = true;
    };
    # Power-menu graceful exit (PowerMenu.qml): snapshot the session + "click the
    # [x]" on every window (hyprvtb dispatcher) and wait for them to close, so
    # logout/reboot/poweroff let apps save and the next login restores positions.
    "quickshell/scripts/session-exit.sh" = {
      source = ./quickshell-files/scripts/session-exit.sh;
      executable = true;
    };
    # Per-host branch point for the panel (e.g. the default desktop-widget set
    # in shell.qml's _defaultWidgets). A generated singleton, mirroring
    # hypr/host.lua — regenerated every switch rather than a seeded-once file,
    # so it always reflects the machine it was built for. Not a source .qml, so
    # it never collides with the qmlFiles readDir above.
    "quickshell/Host.qml".text = ''
      pragma Singleton
      import QtQuick

      QtObject {
          readonly property string name: "${host}"
      }
    '';
  };

  home.packages = [ settings ];

  # Desktop entry so the Settings program is discoverable in the Quickshell
  # runner (DesktopEntries), same approach as filer.nix (xdg.enable is off, so
  # this goes via home.file). `show` — not `toggle` — so launching from the
  # runner always opens it.
  home.file.".local/share/applications/quickshell-settings.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=settings
    GenericName=Desktop Settings
    Comment=Configure the Quickshell desktop
    Exec=${settings}/bin/settings show
    Icon=preferences-desktop
    Terminal=false
    Categories=Settings;DesktopSettings;
    Keywords=bespoke;
  '';

  home.activation.seedQuickshellTheme = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    [ -e "$HOME/.config/quickshell/Theme.qml" ] || install -D -m644 ${./quickshell-files/Theme.qml} "$HOME/.config/quickshell/Theme.qml"
  '';

  # The panel (bar + launcher + tray + clock, and it draws the wallpaper) runs
  # as its OWN systemd user service instead of a one-shot Hyprland exec-once, so
  # a crash, an OOM kill, or a stray `qs kill` can no longer leave the desktop
  # with no panel and no wallpaper until a manual relaunch. hyprland.lua starts
  # it at session start (reset-failed + start) rather than WantedBy a target:
  # nothing activates graphical-session.target in this Hyprland session.
  #
  # Restart=always, not on-failure: a `qs kill` (and a plain SIGTERM) exits the
  # panel *cleanly* — measured, exit 0 — and on-failure would not catch either,
  # yet those are exactly the deaths the reboot of this to a service is meant to
  # survive. StartLimit bounds it: five deaths in a minute (a genuinely broken
  # panel, or logout tearing the compositor out from under it) and systemd stops
  # retrying; the next session's reset-failed re-arms it. RestartSec=1 → ~1s
  # recovery from a one-off death. An intentional stop still goes through
  # `systemctl --user stop`, which never triggers a restart.
  #
  # ExecStart runs through hypr-session-env.sh (same wrapper as wal-set.service)
  # because the manager's HYPRLAND_INSTANCE_SIGNATURE / WAYLAND_DISPLAY are not
  # trustworthy — a nested test compositor overwrites that store; the wrapper
  # resolves the live session from its lockfile instead. Not `qs -d`: daemonizing
  # detaches the shell from systemd, which would then never see it die.
  systemd.user.services.quickshell-panel = {
    Unit = {
      Description = "Quickshell desktop panel + wallpaper";
      After = [ "graphical-session.target" ];
      StartLimitIntervalSec = 60;
      StartLimitBurst = 5;
    };
    Service = {
      Environment = [ "QS_NO_RELOAD_POPUP=1" ];
      ExecStart = "%h/.config/scripts/hypr-session-env.sh ${qsBin}";
      Restart = "always";
      RestartSec = 1;
      # OOMPolicy=continue, because the panel's cgroup is not just the panel.
      # Apps launched from it (the runner, a taskbar action) inherit this unit's
      # cgroup, so their memory is accounted here and their deaths are reported
      # here. systemd's default OOMPolicy=stop fails the unit when the kernel
      # OOM-kills ANY process in it — main process or not — and Restart=always
      # then restarts, which SIGKILLs the whole cgroup: every app he opened from
      # the panel dies with it. Measured on book 2026-08-02: a QtWebEngineProc
      # renderer (oom_score_adj 300, surfer's) was the kernel's victim at 22:12
      # and again at 22:19; `qs` itself was never touched, yet both times the
      # journal reads "killed some processes in this unit" -> "Failed with
      # result 'oom-kill'" -> restart. That is the "desktop crashes and restarts
      # every couple of minutes, losing all my windows" he reported. With
      # `continue`, only the main process being killed counts as a unit OOM.
      OOMPolicy = "continue";
    };
  };
}
