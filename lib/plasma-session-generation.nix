# Ly keeps session commands in memory across system switches. Resolve Plasma
# through the active generation, so startplasma and its systemd units agree.
{ lib, pkgs, ... }:
let
  plasma = pkgs.kdePackages.plasma-workspace;
  launcher = pkgs.writeShellScriptBin "start-plasma-current-generation" ''
    exec ${plasma}/libexec/plasma-dbus-run-session-if-needed \
      ${plasma}/bin/startplasma-wayland "$@"
  '';
  sessions = pkgs.runCommand "plasma-current-generation-sessions" {
    inherit (plasma) providedSessions;
  } ''
    cp -r ${plasma.sessions}/. "$out"
    chmod -R u+w "$out"
    substituteInPlace "$out/share/wayland-sessions/plasma.desktop" \
      --replace-fail 'Exec=${plasma}/libexec/plasma-dbus-run-session-if-needed ${plasma}/bin/startplasma-wayland' \
        'Exec=/run/current-system/sw/bin/start-plasma-current-generation' \
      --replace-fail 'TryExec=${plasma}/bin/startplasma-wayland' \
        'TryExec=/run/current-system/sw/bin/start-plasma-current-generation'
  '';
  # An already running KWin may still search an old Plasma data directory
  # first. A distinct desktop ID lets its permission check find the current
  # shell without shadowing the old shell's entry or relaxing permissions.
  shellIdentity = pkgs.runCommand "plasma-current-generation-identity" { } ''
    mkdir -p "$out/share/applications"
    cp ${plasma}/share/applications/org.kde.plasmashell.desktop \
      "$out/share/applications/org.kde.plasmashell-current-system.desktop"
    substituteInPlace "$out/share/applications/org.kde.plasmashell-current-system.desktop" \
      --replace-fail 'Exec=${plasma}/bin/plasmashell' \
        'Exec=/run/current-system/sw/bin/plasmashell'
    grep -qx 'NoDisplay=true' "$out/share/applications/org.kde.plasmashell-current-system.desktop"
  '';
in
{
  options.services.displayManager.sessionPackages = lib.mkOption {
    apply = packages: map (package:
      if toString package == toString plasma.sessions then sessions else package
    ) packages;
  };
  config.environment.systemPackages = [ launcher shellIdentity ];
}
