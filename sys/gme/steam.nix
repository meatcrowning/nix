{ config, pkgs, user, ... }:

{
  programs.steam = {
    enable = true;
    remotePlay.openFirewall = true;
    # dedicatedServer stays closed: hosting a Source dedicated server (27015)
    # isn't something this desktop does, and every steam openFirewall flag opens
    # its ports on ALL interfaces (incl. tailscale0), unlike the rest of the box.
    dedicatedServer.openFirewall = false;
    localNetworkGameTransfers.openFirewall = true;
  };

  # PS2 Startup [LCD] by ToppySmells, steamdeckrepo.com/post/nObL9.
  # Selection and Start in Big Picture remain Steam-owned client settings.
  home-manager.users.${user}.home.file.".local/share/Steam/config/uioverrides/movies/ps2_startup.webm".source = pkgs.fetchurl {
    url = "https://steamdeckrepo.s3.us-west-004.backblazeb2.com/videos/lv8ReRMd6GkIR9r8gD390OfKsp0p3uFt2W4fCg6J.webm";
    hash = "sha256-etAklo9/xLDmrgPkj0M/6jGElSei35jgeIHUQvl2gyo=";
  };
}
