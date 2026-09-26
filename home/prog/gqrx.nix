{ lib, pkgs, host, ... }:

# book only: gqrx on top's RTL-SDR dongle (sys/hw/rtl-sdr.nix). Top runs its
# own gqrx from systemPackages; see gqrx-files/gqrx-top.sh for the transport.
lib.mkIf (host == "air") {
  home.packages = [
    pkgs.gqrx
    (pkgs.writeShellScriptBin "gqrx-top" (builtins.readFile ./gqrx-files/gqrx-top.sh))
  ];

  xdg.desktopEntries.gqrx-top = {
    name = "Gqrx (top)";
    genericName = "Software defined radio";
    exec = "gqrx-top";
    icon = "gqrx";
    categories = [ "AudioVideo" "Audio" "HamRadio" ];
  };
}
