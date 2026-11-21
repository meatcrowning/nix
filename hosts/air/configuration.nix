{ config, pkgs, lib, inputs, user, privateConfig, ... }:

# book (flake attr `air`) as NixOS on its M1. Standalone like pad: sys/ is
# top's whole desktop (NVIDIA, ollama, Steam), so only what book needs is here.
# The shared user configuration arrives through home-manager (flake.nix).
{
  imports = [
    ./hardware-configuration.nix
    ./fairydust.nix
    ./kwin-momentum.nix
    ./video.nix
    ./music-share.nix
    inputs.apple-silicon.nixosModules.apple-silicon-support
  ];

  hardware.asahi = {
    enable = true;
    # Load the ESP's vendorfw/firmware.cpio in the initrd, so Apple's
    # non-redistributable firmware never enters the store or this repo.
    peripheralFirmwareDirectory = null;
    # nixos-apple-silicon publishes no cache. top cross-builds the kernel,
    # m1n1 and U-Boot through the restricted builder instead of book's 7G.
    pkgsSystem = "x86_64-linux";
  };

  boot.loader = {
    systemd-boot = {
      enable = true;
      # The 500M ESP also holds the Asahi firmware and m1n1's stage 2, which
      # the apple-silicon module installs here with device trees matching
      # this kernel.
      configurationLimit = 3;
    };
    efi.canTouchEfiVariables = false;
  };

  networking = {
    hostName = "book";
    networkmanager.enable = true;
  };
  services.resolved.enable = true;

  # top's builder and SMB share resolve as `top` over the tailnet.
  services.tailscale.enable = true;

  time.timeZone = privateConfig.location.timeZone;
  i18n.defaultLocale = "en_US.UTF-8";

  users.users.${user} = {
    isNormalUser = true;
    description = user;
    extraGroups = [ "networkmanager" "wheel" "video" "input" ];
    shell = pkgs.zsh;
  };
  programs.zsh.enable = true;

  services = {
    displayManager.ly.enable = true;
    displayManager.defaultSession = "plasma";
    desktopManager.plasma6.enable = true;
    pipewire = {
      enable = true;
      alsa.enable = true;
      pulse.enable = true;
    };
    pulseaudio.enable = false;
    flatpak.enable = true;
    udisks2.enable = true;
    fstrim.enable = true;
    upower.enable = true;
  };
  security.rtkit.enable = true;
  hardware.bluetooth.enable = true;
  # Stop charging at 80% to slow battery wear.
  services.udev.extraRules = ''
    ACTION=="add|change", SUBSYSTEM=="power_supply", KERNEL=="macsmc-battery", ATTR{charge_control_end_threshold}="80"
  '';
  # macOS-style memory: compress early and deep, spill to disk only after zram.
  zramSwap = { enable = true; memoryPercent = 100; priority = 100; };
  swapDevices = [{ device = "/var/lib/swapfile"; size = 4096; priority = 1; }];
  boot.kernel.sysctl = {
    "vm.swappiness" = 180; # zram is cheaper than dropping page cache
    "vm.page-cluster" = 0; # no swap readahead; zram has no seek cost
    "vm.watermark_boost_factor" = 0;
    "vm.watermark_scale_factor" = 125;
  };
  # PSI-based kills in the user slices before 7.3G runs out (sys/oomd.nix).
  systemd.oomd.enableUserSlices = true;

  # KDE Connect, on Wi-Fi only (top scopes it to its wired LAN the same way).
  networking.firewall.interfaces.wld0 = {
    allowedTCPPortRanges = [{ from = 1714; to = 1764; }];
    allowedUDPPortRanges = [{ from = 1714; to = 1764; }];
  };

  fonts = {
    enableDefaultPackages = true;
    fontDir.enable = true;
    packages = [ pkgs.noto-fonts-cjk-sans ];
  };

  environment.systemPackages = with pkgs; [ git vim btrfs-progs asahi-bless ];

  nix = {
    settings = {
      experimental-features = [ "nix-command" "flakes" "pipe-operators" ];
      auto-optimise-store = true;
      trusted-users = [ "root" user ];
      builders-use-substitutes = true;
      # top's store, reached with the same restricted key as its builder.
      extra-substituters = [
        "ssh://nix-ssh@top?ssh-key=/etc/nix/book-builder-key&trusted=true"
      ];
    };
    distributedBuilds = true;
    buildMachines = [{
      hostName = "top";
      sshUser = "nix-ssh";
      sshKey = "/etc/nix/book-builder-key";
      protocol = "ssh";
      system = "x86_64-linux";
      maxJobs = 1;
      supportedFeatures = [ "big-parallel" ];
    }];
    gc = {
      automatic = true;
      dates = "weekly";
      options = "--delete-older-than 14d";
    };
  };
  # /etc/nix/book-builder-key is machine state, not in the store; the host key
  # is pinned.
  programs.ssh.knownHosts.top = {
    hostNames = [ "top" ];
    publicKey = privateConfig.builderHostKey;
  };

  # 7.3G shared with the GPU: a local build may fail, never take the session.
  # Measured on 2026-08-02: an unbounded compositor build tripped a global
  # oom-kill; at --cores 4 under this cap it peaked at 3.78G.
  systemd.services.nix-daemon.serviceConfig = {
    MemoryHigh = "3.5G";
    MemoryMax = "5G";
    OOMScoreAdjust = 500;
  };

  nixpkgs.config.allowUnfree = true;
  system.stateVersion = "25.11";
}
