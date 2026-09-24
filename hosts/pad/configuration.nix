{ pkgs, user, ... }:
{
  imports = [ ./hardware-configuration.nix ./desktop.nix ];
  networking.hostName = "pad";
  networking.networkmanager.enable = true;
  networking.firewall.enable = true;
  nixpkgs.config.allowUnfree = true;
  nix.settings = {
    experimental-features = [ "nix-command" "flakes" ];
    max-jobs = 1;
    cores = 2;
    auto-optimise-store = true;
  };
  nix.gc = { automatic = true; dates = "weekly"; options = "--delete-older-than 14d"; };
  systemd.services.nix-daemon.serviceConfig = {
    MemoryHigh = "2G";
    MemoryMax = "3G";
    OOMScoreAdjust = 500;
  };
  zramSwap = { enable = true; algorithm = "lz4"; memoryPercent = 50; };
  services.journald.settings.Journal.SystemMaxUse = "200M";
  services.power-profiles-daemon.enable = true;
  services.upower.enable = true;
  services.fstrim.enable = true;
  services.logind.settings.Login.HandleLidSwitch = "suspend";
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    pulse.enable = true;
  };
  security.rtkit.enable = true;
  services.udisks2.enable = true;
  services.gvfs.enable = true;
  hardware.bluetooth.enable = true;
  hardware.bluetooth.powerOnBoot = false;
  services.blueman.enable = true;
  i18n.defaultLocale = "en_US.UTF-8";
  # Set the local timezone with timedatectl after installation.
  time.timeZone = null;
  users.users.${user} = {
    isNormalUser = true;
    extraGroups = [ "wheel" "networkmanager" ];
    # Set with nixos-enter --root /mnt -c 'passwd lam' before first boot.
  };
  services.openssh = {
    enable = true;
    settings = { PasswordAuthentication = false; KbdInteractiveAuthentication = false; PermitRootLogin = "prohibit-password"; };
    # Provision top's public deployment key here, outside the public repository.
    authorizedKeysFiles = [ "/etc/ssh/authorized_keys.d/%u" ];
  };
  environment.systemPackages = with pkgs; [ git curl nano ];
  system.stateVersion = "26.05";
}
