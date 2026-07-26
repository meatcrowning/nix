{ config, pkgs, ... }:

{
  nix = {
    settings = {
      experimental-features = [ "nix-command" "flakes" "pipe-operators" ];
      auto-optimise-store = true;
      # Defaults were max-jobs=auto(16) x cores=0(all 16): up to 16 parallel
      # derivations each spawning -j16 thrashes the 16-thread CPU and 30G RAM
      # on big uncached updates. Cap the product near the thread count.
      max-jobs = 4;
      cores = 8;
      # These must be in `substituters` (the active query list), NOT only
      # `trusted-substituters` — the latter merely *permits* opting in and is
      # never consulted, so the CUDA deps of the git-CUDA ollama overlay were
      # compiling locally. Listing them here makes them actual download sources.
      substituters = [
        "https://cache.nixos.org"
        "https://cuda-maintainers.cachix.org"
        "https://ai.cachix.org"
        # Hyprland now comes from the pinned hyprwm flake (see flake.nix), not
        # nixpkgs, so cache.nixos.org has no build for it. This is upstream's
        # own cache and it only hits when the hyprwm inputs are left
        # unmodified — which is why the `hyprland` input deliberately does NOT
        # `follows`-pin nixpkgs.
        "https://hyprland.cachix.org"
      ];
      trusted-substituters = [
        "https://ai.cachix.org"
        "https://cuda-maintainers.cachix.org"
        "https://hyprland.cachix.org"
      ];
      trusted-public-keys = [
        "ai.cachix.org-1:N9dzRK+alWwoKXQlnn0H6aUx0lU/mspIoz8hMvGvbbc="
        "cuda-maintainers.cachix.org-1:0dq3bujKpuEPMCX6U4WylrUDZ9JyUG0VpVZa7CNfq5E="
        "hyprland.cachix.org-1:a7pgxzMz7+chwVL3/pzj6jIBMioiJM7ypFP8PwtkuGc="
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
    # Root SSD runs full; wipe /tmp on boot so build temp dirs don't accumulate.
    # (cleanOnBoot rather than useTmpfs: local LLMs + heavy CUDA builds shouldn't
    # compete with a RAM-backed /tmp.)
    tmp.cleanOnBoot = true;
  };

  # Disk / SSD hygiene for the perpetually-full root:
  services.fstrim.enable = true;                            # periodic TRIM
  services.journald.extraConfig = "SystemMaxUse=500M";      # cap journal growth
  zramSwap.enable = true;                                   # RAM-compressed swap
                                                            # ahead of the on-disk swapfile

  time.timeZone = "America/Juneau";
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
