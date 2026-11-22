{ pkgs, ... }:

# Steam on book. x86 code needs 4K pages and book's kernel uses 16K, so
# Steam runs in a muvm microVM (4K guest kernel) under FEX. The guest sees the
# host store, so nixpkgs' own x86_64 Steam FHS env runs unchanged; top's
# builder covers what the binary cache lacks. Games reach the GPU through x86
# Mesa's Honeykrisp/asahi drivers over virtio-gpu native context.
let
  x86 = import pkgs.path {
    system = "x86_64-linux";
    config.allowUnfree = true;
  };

  # muvm 0.6.0 registers binfmt for FEXInterpreter; FEX 2608 ships it as FEX.
  fexShim = pkgs.runCommand "fex-interpreter-shim" { } ''
    mkdir -p $out/bin
    ln -s ${pkgs.fex}/bin/FEX $out/bin/FEXInterpreter
  '';

  # Runs as root in the guest after muvm's own init, which points
  # /run/opengl-driver at the host's aarch64 drivers.
  guestInit = pkgs.writeShellScript "muvm-x86-drivers" ''
    ln -sfn ${x86.mesa} /run/opengl-driver
    ln -sfn ${x86.pkgsi686Linux.mesa} /run/opengl-driver-32
  '';

  # The guest cannot reach the host's session bus, and SteamRT3's launcher
  # service exits without one.
  guestSteam = pkgs.writeShellScript "steam-guest" ''
    exec ${pkgs.dbus}/bin/dbus-run-session -- ${x86.steam}/bin/steam "$@"
  '';

  launcher = pkgs.writeShellScriptBin "steam" ''
    export PATH=${fexShim}/bin:$PATH
    exec ${pkgs.muvm}/bin/muvm --execute-pre=${guestInit} -- ${guestSteam} "$@"
  '';

  steam = pkgs.runCommand "steam-muvm" { } ''
    mkdir -p $out
    ln -s ${launcher}/bin $out/bin
    ln -s ${x86.steam}/share $out/share
  '';
in
{
  environment.systemPackages = [ steam ];
  services.udev.packages = [ pkgs.steam-devices-udev-rules ];
}
