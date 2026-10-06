{ config, lib, pkgs, privateConfig, ... }:

let
  # Drives declared in sys/disks.nix are mounted by systemd at fixed paths.
  # udiskie must never automount them: on 2026-10-05 it grabbed the replugged
  # music SSD at /run/media/lam/SSD1 while the stale mount still held SSD, and
  # player plus the SMB share lost the library. udiskie ignores udisks' HintAuto,
  # so this has to be its own device_config.
  fstabUuids = map (lib.removePrefix "/dev/disk/by-uuid/")
    (lib.attrValues (removeAttrs privateConfig.devices [ "root" "boot" ]));
in
{
  services.udiskie = {
    enable = true;
    notify = false; # mount/unmount toasts are noise
    settings = {
      program_options = {
        file_manager = "${pkgs.kdePackages.dolphin}/bin/dolphin";
      };
      device_config = map (u: { id_uuid = u; automount = false; }) fstabUuids;
    };
  };
}
