{ config, pkgs, lib, host, ... }:

let
  qmlDir = ./quickshell-files;

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
  '';

  home.activation.seedQuickshellTheme = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    [ -e "$HOME/.config/quickshell/Theme.qml" ] || install -D -m644 ${./quickshell-files/Theme.qml} "$HOME/.config/quickshell/Theme.qml"
  '';
}
