{ config, pkgs, lib, host, ... }:

let
  qmlDir = ./quickshell-files;
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

  home.activation.seedQuickshellTheme = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    [ -e "$HOME/.config/quickshell/Theme.qml" ] || install -D -m644 ${./quickshell-files/Theme.qml} "$HOME/.config/quickshell/Theme.qml"
  '';
}
