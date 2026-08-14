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
      # never consulted, so the CUDA deps of ollama-cuda (sys/ai/ollama.nix)
      # would otherwise compile locally. Listing them here makes them actual
      # download sources.
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
      # memtest86: `top` has a marginal DRAM data line (every measured flip is
      # bit 18 of a 32-bit word) that no ECC/EDAC on this board can report, so
      # the loader entry is the only fast feedback loop for testing a fix.
      # Adds a menu entry only; the default boot is unchanged.
      systemd-boot = {
        enable = true;
        configurationLimit = 15;
        memtest86.enable = true;
      };
      efi.canTouchEfiVariables = true;
    };
    kernelPackages = pkgs.linuxPackages_latest;
    plymouth.enable = false;
    # Root SSD runs full; wipe /tmp on boot so build temp dirs don't accumulate.
    # (cleanOnBoot rather than useTmpfs: local LLMs + heavy CUDA builds shouldn't
    # compete with a RAM-backed /tmp.)
    tmp.cleanOnBoot = true;
  };

  # Disallow replacing the running kernel image at runtime: disables kexec
  # (kernel.kexec_load_disabled=1) and adds `nohibernate`. Free here — nothing
  # kexecs, and there is no `resume=`/hibernation to break (swap is
  # randomEncryption'd, which rules hibernation out anyway).
  security.protectKernelImage = true;

  # Disk / SSD hygiene for the perpetually-full root:
  services.fstrim.enable = true;                            # periodic TRIM
  # Cap journal growth, but keep a longer forensic window than 500M gave (that
  # was already full, so auth/sudo history rotated in ~a week). 1G roughly
  # doubles the trail for spotting a late-noticed compromise; trivial on a 1.8T
  # root that currently sits ~72% used.
  services.journald.extraConfig = "SystemMaxUse=1G";
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
