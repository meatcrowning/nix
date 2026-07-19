{ config, pkgs, ... }:

{
  nix = {
    settings = {
      experimental-features = [ "nix-command" "flakes" "pipe-operators" ];
      auto-optimise-store = true;
      trusted-substituters = [
        "https://ai.cachix.org"
        "https://cuda-maintainers.cachix.org"
      ];
      trusted-public-keys = [
        "ai.cachix.org-1:N9dzRK+alWwoKXQlnn0H6aUx0lU/mspIoz8hMvGvbbc="
        "cuda-maintainers.cachix.org-1:0dq3bujKpuEPMCX6U4WylrUDZ9JyUG0VpVZa7CNfq5E="
      ];
    };
    # nix-collect-garbage wants a period like "14d" here; the old value "+10"
    # (nix-env generation syntax) made the weekly nix-gc.service fail for months.
    gc = {
      automatic = true;
      dates = "weekly";
      options = "--delete-older-than 14d";
    };
  };

  boot = {
    loader = {
      systemd-boot = { enable = true; configurationLimit = 15; };
      efi.canTouchEfiVariables = true;
    };
    kernelPackages = pkgs.linuxPackages_latest;
    plymouth.enable = false;
  };

  time.timeZone = "Etc/UTC";
  i18n.defaultLocale = "en_US.UTF-8";

  networking = {
    networkmanager.enable = true;
    # jellyfin settings, disabled for now because i dont know if i really want to use it but what else is there as a media server lol oh i guess plex
    #firewall = {
    #  allowedTCPPorts = [ 8096 8920 ]; # HTTP and HTTPS
    #  allowedUDPPorts = [ 1900 7359 ]; # DLNA and Auto-discovery
    #};
  };

  nixpkgs.config.allowUnfree = true;
  # nixpkgs.config.permittedInsecurePackages = [ "olm-3.2.16" ];

  system.stateVersion = "25.11";
}
