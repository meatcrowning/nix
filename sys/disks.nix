{ pkgs, ... }:

let
  # Relabel a filesystem (the "rename drive" action in the disk popup).
  # Per-fstype tool; btrfs relabels online via the mountpoint. Invoked as
  # `sudo drive-label <device> <fstype> <newlabel>` (NOPASSWD rule below).
  driveLabel = pkgs.writeShellScriptBin "drive-label" ''
    dev="$1"; fstype="$2"; label="$3"
    [ -n "$dev" ] && [ -n "$fstype" ] || { echo "usage: drive-label <dev> <fstype> <label>" >&2; exit 2; }
    case "$fstype" in
      btrfs)
        mp=$(${pkgs.util-linux}/bin/findmnt -n -o TARGET --source "$dev" | head -n1)
        if [ -n "$mp" ]; then ${pkgs.btrfs-progs}/bin/btrfs filesystem label "$mp" "$label"
        else ${pkgs.btrfs-progs}/bin/btrfs filesystem label "$dev" "$label"; fi ;;
      ext2|ext3|ext4) ${pkgs.e2fsprogs}/bin/e2label "$dev" "$label" ;;
      exfat)          ${pkgs.exfatprogs}/bin/exfatlabel "$dev" "$label" ;;
      vfat|fat)       ${pkgs.dosfstools}/bin/fatlabel "$dev" "$label" ;;
      *) echo "unsupported fstype: $fstype" >&2; exit 1 ;;
    esac
  '';
in
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
    # The music library SSD. udisks mounted this only while a desktop session
    # was up; sys/net/share.nix serves it over SMB to `air`, which needs it
    # present from boot. Options match what udisks was already using, so the
    # mount path — and therefore every tracks.path in the player's database —
    # is unchanged. Escape hatch: delete this entry and udisks resumes its old
    # session-scoped behaviour.
    "/run/media/lam/SSD" = {
      device = "/dev/disk/by-uuid/0068-1FA0";
      fsType = "exfat";
      options = [ "nofail" "x-systemd.device-timeout=5s"
                  "uid=1000" "gid=100" "fmask=0022" "dmask=0022" "iocharset=utf8" ];
    };
    "/home/lam/drives/cld" = {
      device = "/dev/disk/by-uuid/7f022945-5aba-4d0e-8a42-fa5be19292f4";
      fsType = "btrfs";
      options = [ "nofail" "x-systemd.device-timeout=5s" ];
    };
    "/home/lam/drives/linux-old" = {
      device = "/dev/disk/by-uuid/41510f82-e570-461f-af0a-91dfcdee6376";
      fsType = "btrfs";
      options = [ "nofail" "x-systemd.device-timeout=5s" "subvolid=5" ];
    };
    "/home/lam/drives/nixos-old" = {
      device = "/dev/disk/by-uuid/2364de91-8173-4512-b004-1f109b620a55";
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
    commands = [
      { command = "${pkgs.smartmontools}/bin/smartctl"; options = [ "NOPASSWD" ]; }
      { command = "${driveLabel}/bin/drive-label"; options = [ "NOPASSWD" ]; }
    ];
  }];

  environment.systemPackages = [ pkgs.smartmontools pkgs.jq driveLabel ];
}
