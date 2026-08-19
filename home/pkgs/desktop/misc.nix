{ pkgs, lib, ... }:

let
  isX86 = pkgs.stdenv.hostPlatform.isx86_64;
in
{
  home.packages = with pkgs; [
    # nheko
    # retroarch-full
    # XBOX EMU xenia-canary
    sillytavern
    # open-webui
  ] ++ lib.optionals isX86 [
    discord
    # vcv-rack   # off for now: the vcv-rack-overlay drops a patch, so it has no
                 # cache hit and compiles from source on every nixpkgs roll
    vintagestory
    pcsx2
  ];
}
