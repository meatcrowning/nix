{ config, pkgs, lib, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ../../sys
  ];

  # AeroThemePlasma: installed, and offered in ly's session list. hyprland
  # stays the default session — this only adds a choice at the greeter.
  my.aerotheme.enable = true;

  networking.hostName = "top";
  # 38899 is WiZ smart-bulb control, which is UDP and outbound — nothing on this
  # host listens on TCP 38899, so only the UDP rule is needed.
  networking.firewall.allowedUDPPorts = [ 38899 ];

  swapDevices = [{
    device = "/var/lib/swapfile";
    size = 16*1024; # 16 GB
    # Fresh random key each boot, so RAM paged to the unencrypted root SSD never
    # persists in cleartext (the disk itself is not LUKS). Safe here because
    # nothing hibernates — there is no `resume=` on the kernel cmdline — and
    # zram is the primary swap anyway (this file is priority -1).
    randomEncryption.enable = true;
  }];

  services = {
    udisks2.enable = true;
    printing.enable = true;
    pulseaudio.enable = false;
    flatpak.enable = true;
    pipewire = {
      enable = true;
      alsa = { enable = true; support32Bit = true; };
      pulse.enable = true;
      # Stop WirePlumber suspending idle audio nodes: the DAC powering back
      # up on wake produces an audible click at the start of playback.
      wireplumber.extraConfig."51-disable-suspend" = {
        "monitor.alsa.rules" = [{
          matches = [{ "node.name" = "~alsa_(output|input).*"; }];
          actions.update-props."session.suspend-timeout-seconds" = 0;
        }];
      };
    };
    hardware.openrgb.enable = true;
  };

  security.rtkit.enable = true;

  # No `programs.kdeconnect.enable` on purpose: it opens 1714-1764 on every
  # interface with no opt-out. sys/net/kdeconnect.nix opens the same range
  # scoped to the LAN; the package comes from home/pkgs/desktop/kde.nix.

  fonts = {
    packages = with pkgs; [
      noto-fonts-cjk-sans
    ];
    enableDefaultPackages = true;
    fontconfig.enable = true;
    fontDir.enable = true;
  };

  environment.etc."xdg/sound-theme.ini".text = ''
    [Theme]
    Name=Default
    Inherits=freedesktop
  '';
}
