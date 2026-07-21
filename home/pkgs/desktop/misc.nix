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
    vcv-rack
    vintagestory
    pcsx2
  ];
}
