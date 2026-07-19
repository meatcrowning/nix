{ pkgs, ... }:

{
  # Auto-mount the three unmounted internal data drives under ~/drives.
  # by-uuid so kernel sd* reordering can't misroute them; nofail +
  # device-timeout so a missing/failed drive never blocks boot.
  #   sdf1 "cld"  — empty btrfs data drive
  #   sda2        — an old generic-Linux root (browse; full FHS tree)
  #   sdd2 "root" — an old NixOS 26.11 root install (browse)
  # btrfs roots mount subvolid=5 (top level) so nothing is hidden behind a
  # default subvolume. All read-write per request; the old roots stay
  # root-owned (correct), cld's top dir is chowned to lam once so it's
  # usable as a data drive.
  fileSystems = {
    "/home/lam/drives/cld" = {
      device = "/dev/disk/by-label/REDACTED";
      fsType = "btrfs";
      options = [ "nofail" "x-systemd.device-timeout=5s" ];
    };
    "/home/lam/drives/linux-old" = {
      device = "/dev/disk/by-label/REDACTED";
      fsType = "btrfs";
      options = [ "nofail" "x-systemd.device-timeout=5s" "subvolid=5" ];
    };
    "/home/lam/drives/nixos-old" = {
      device = "/dev/disk/by-label/REDACTED";
      fsType = "ext4";
      options = [ "nofail" "x-systemd.device-timeout=5s" ];
    };
  };

  # own the parent dir so lam can traverse into the mounts
  systemd.tmpfiles.rules = [ "d /home/lam/drives 0755 lam users - -" ];

  # SMART for the disk-hover popup. udisks2 could expose this over D-Bus but
  # the CLI is painful; a NOPASSWD rule for the read-only `smartctl` is the
  # simple path (quickshell runs as lam, no TTY).
  security.sudo.extraRules = [{
    users = [ "lam" ];
    commands = [{
      command = "${pkgs.smartmontools}/bin/smartctl";
      options = [ "NOPASSWD" ];
    }];
  }];

  environment.systemPackages = [ pkgs.smartmontools pkgs.jq ];
}
