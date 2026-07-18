{ pkgs, ... }:

{
  home.packages = with pkgs; [
    discord
    # nheko
    vcv-rack
    vintagestory
    pcsx2
    # retroarch-full
    # XBOX EMU xenia-canary
    sillytavern
    # open-webui
  ];
}
