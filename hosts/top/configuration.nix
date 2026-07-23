{ config, pkgs, lib, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ../../sys
  ];

  # toggle for aerothemeplasma-nix
  #my.aerotheme.enable = true;

  networking.hostName = "top";
  # 38899 is WiZ smart-bulb control, which is UDP and outbound — nothing on this
  # host listens on TCP 38899, so only the UDP rule is needed.
  networking.firewall.allowedUDPPorts = [ 38899 ];

  swapDevices = [{
    device = "/var/lib/swapfile";
    size = 16*1024; # 16 GB
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
    };
    hardware.openrgb.enable = true;
  };

  security.rtkit.enable = true;
  virtualisation.vmware.host.enable = true;

  programs.kdeconnect.enable = true;

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
