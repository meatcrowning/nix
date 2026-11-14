{ config, pkgs, lib, inputs, user, privateConfig, ... }:

# book (flake attr `air`) as NixOS on its M1. Standalone like pad: sys/ is
# top's whole desktop (NVIDIA, ollama, Steam), so only what book needs is here.
# The shared user configuration arrives through home-manager (flake.nix).
{
  imports = [
    ./hardware-configuration.nix
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

  # Same tailnet node as Fedora's (the state directory is copied at install),
  # so top's builder and SMB share resolve as `top` without a new login.
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
  zramSwap.enable = true;

  fonts = {
    enableDefaultPackages = true;
    fontDir.enable = true;
    packages = [ pkgs.noto-fonts-cjk-sans ];
  };

  environment.systemPackages = with pkgs; [ git vim btrfs-progs asahi-bless ];

  nix = {
    settings = {
      experimental-features = [ "nix-command" "flakes" "pipe-operators" ];
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
  # The key is copied from Fedora's /etc/nix at install; the host key is pinned.
  programs.ssh.knownHosts.top = {
    hostNames = [ "top" ];
    publicKey = privateConfig.builderHostKey;
  };

  # 7.3G shared with the GPU: a local build may fail, never take the session
  # (docs/agents/book-fedora-state.md, nix-daemon memory cap).
  systemd.services.nix-daemon.serviceConfig = {
    MemoryHigh = "3.5G";
    MemoryMax = "5G";
    OOMScoreAdjust = 500;
  };

  nixpkgs.config.allowUnfree = true;
  system.stateVersion = "25.11";
}
