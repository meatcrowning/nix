{ config, host, lib, pkgs, ... }:
let
  project = "${config.home.homeDirectory}/Projects/cod-offline";
  launcher = pkgs.writeShellApplication {
    name = "iw4x-offline";
    runtimeInputs = [ pkgs.wineWow64Packages.stable pkgs.python3 pkgs.coreutils
      pkgs.util-linux pkgs.bubblewrap pkgs.imagemagick ];
    text = ''
      export IW4X_DXVK=${pkgs.dxvk.bin}
      exec bash ${lib.escapeShellArg "${project}/launch.sh"} "$@"
    '';
  };
in {
  # The source game and independent offline project are installed on top.
  config = lib.mkIf (host == "top") {
    home.packages = [ launcher ];
    xdg.desktopEntries.iw4x-offline = {
      name = "IW4x — Offline";
      comment = "Custom loadouts and offline bot matches";
      exec = "${launcher}/bin/iw4x-offline";
      icon = "${project}/art/icon.svg";
      categories = [ "Game" ];
      terminal = false;
      settings.StartupWMClass = "iw4x.exe";
    };
  };
}
