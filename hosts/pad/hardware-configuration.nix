{ lib, pkgs, modulesPath, ... }:
{
  imports = [ (modulesPath + "/installer/scan/not-detected.nix") ];
  nixpkgs.hostPlatform = lib.mkDefault "x86_64-linux";
  boot.initrd.availableKernelModules = [ "xhci_pci" "ahci" "usb_storage" "sd_mod" ];
  boot.kernelModules = [ "kvm-intel" ];
  hardware.cpu.intel.updateMicrocode = true;
  hardware.enableRedistributableFirmware = true;
  hardware.graphics = {
    enable = true;
    # Bay Trail uses the older i965 VA-API driver.
    extraPackages = [ pkgs.intel-vaapi-driver ];
  };
  boot.loader.systemd-boot = { enable = true; configurationLimit = 2; };
  boot.loader.efi.canTouchEfiVariables = true;
  # Installation contract, not the current Arch partition UUIDs. Mount the
  # chosen NixOS root/ESP with these labels or replace this file after scanning.
  fileSystems."/" = { device = "/dev/disk/by-label/nixos"; fsType = "ext4"; };
  fileSystems."/boot" = { device = "/dev/disk/by-label/BOOT"; fsType = "vfat"; options = [ "umask=0077" ]; };
  swapDevices = [ { device = "/swapfile"; size = 4096; } ];
}
