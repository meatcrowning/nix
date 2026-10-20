{ lib, pkgs, host, ... }:

# book only: gqrx on top's RTL-SDR dongle (sys/hw/rtl-sdr.nix). Top runs its
# own gqrx from systemPackages; see gqrx-files/gqrx-top.sh for the transport.
# On book install Fedora's gqrx package: sudo dnf install gqrx.
# Its native radio/Qt stack avoids duplicating the full Nix build closure.
lib.mkIf (host == "air") {
  home.packages = [
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
