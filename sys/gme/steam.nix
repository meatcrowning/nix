{ config, pkgs, ... }:

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
}
