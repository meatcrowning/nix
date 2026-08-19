{ pkgs, ... }:

let
  # Relabel a filesystem (the "rename drive" action in the disk popup).
  # Per-fstype tool; btrfs relabels online via the mountpoint. Invoked as
  # `sudo drive-label <device> <fstype> <newlabel>` (NOPASSWD rule below).
  driveLabel = pkgs.writeShellScriptBin "drive-label" ''
    dev="$1"; fstype="$2"; label="$3"
    [ -n "$dev" ] && [ -n "$fstype" ] || { echo "usage: drive-label <dev> <fstype> <label>" >&2; exit 2; }
    # Same guard as drive-smart: resolve and require a real block device before
    # relabelling anything as root.
    dev=$(${pkgs.coreutils}/bin/realpath -e -- "$dev" 2>/dev/null) \
      || { echo "drive-label: no such device" >&2; exit 2; }
    [ -b "$dev" ] || { echo "drive-label: not a block device: $dev" >&2; exit 2; }
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

  # Read-only SMART query for the disk-hover popup. The NOPASSWD rule below
  # points at THIS wrapper, not raw smartctl, so the passwordless-root grant is
  # hardcoded to `smartctl -a -j <device>` (attributes/health/logs/identity, no
  # `-t` self-test, no `--set` toggle) and the device is constrained to a real
  # block node — closing the "arbitrary smartctl args as root" hole while
  # serving the only invocation quickshell actually makes (disk-smart.sh).
  driveSmart = pkgs.writeShellScriptBin "drive-smart" ''
    [ "$#" -eq 1 ] || { echo "usage: drive-smart <device>" >&2; exit 2; }
    # Canonicalise (resolve symlinks + `..`) then require a real BLOCK device.
    # A shell `case` glob would let `/dev/disk/by-id/../../../dev/watchdog`
    # through — a char device whose open() arms the watchdog and reboots the
    # box — so match on the resolved node's type, not on the string.
    dev=$(${pkgs.coreutils}/bin/realpath -e -- "$1" 2>/dev/null) \
      || { echo "drive-smart: no such path" >&2; exit 2; }
    [ -b "$dev" ] || { echo "drive-smart: not a block device: $dev" >&2; exit 2; }
    exec ${pkgs.smartmontools}/bin/smartctl -a -j "$dev"
  '';
in
{
  # Declare every data drive by UUID. Kernel sd* letters are NOT stable here —
  # the two USB drives swapped letters twice in one day (2026-07-26), so by-uuid
  # is the only safe reference. nofail + device-timeout so a missing or failed
  # drive (especially the USB ones) never blocks boot.
  #   "cld"  — btrfs data drive (internal SATA, WD Blue CMR)
  #   "arc"  — 1.8T ext4 archive drive (USB; was UNLABELED and udisks-mounted at
  #            /run/media/lam/<uuid>, a 36-char path that only existed while a
  #            desktop session was up — labelled "arc" and declared 2026-07-26)
  #   "bak"  — 4.6T btrfs backup drive (USB; likewise promoted from a udisks
  #            session mount so it is present from boot)
  #   linux-old — an old generic-Linux root (browse; full FHS tree)
  #   nixos-old — an old NixOS 26.11 root install (browse)
  #
  # NOTE on "bak": its USB bridge DISCARDS cache flushes, so fsync() there is
  # not durable and btrfs loses its write-ordering guarantee (measured: 272
  # fsync IOPS, impossible for a 4800rpm drive; hdparm -W0 drops it to 3).
  # Treat it as write-once archive, unmount cleanly, and never let it hold the
  # only copy. See docs/top-storage-tiers.md §3a.
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
    # The 1.8T archive drive. Mounted under /run/media/lam/ (not ~/drives) so
    # the path is exactly where udisks would put it now that it has a label —
    # deleting this entry falls back to identical behaviour, just session-scoped.
    "/run/media/lam/arc" = {
      device = "/dev/disk/by-uuid/92fb0e4e-3c51-46a8-9b2a-2bd9984409ba";
      fsType = "ext4";
      options = [ "nofail" "x-systemd.device-timeout=10s" "nosuid" "nodev" ];
    };
    # The backup drive. subvolid=5 mounts the btrfs top level so nothing hides
    # behind a default subvolume; discard=async because this bridge does pass
    # TRIM through (unlike the PNY's, which reports no discard support at all).
    "/run/media/lam/bak" = {
      device = "/dev/disk/by-uuid/830705c8-e5ef-48ff-8a2b-560cf1698757";
      fsType = "btrfs";
      options = [ "nofail" "x-systemd.device-timeout=10s" "nosuid" "nodev"
                  "subvolid=5" "discard=async" ];
    };
    # nosuid,nodev like arc/bak: these old-OS roots carry a full FHS tree with
    # 2022 setuid-root binaries (linux-old's /usr/bin/{sudo,pkexec,su,...}).
    # They can't execute on NixOS today (foreign ELF interpreter is absent), but
    # honouring their setuid bit and device nodes is a needless local-privesc
    # reservoir — deny both, matching every other data mount here.
    "/home/lam/drives/linux-old" = {
      device = "/dev/disk/by-uuid/41510f82-e570-461f-af0a-91dfcdee6376";
      fsType = "btrfs";
      options = [ "nofail" "x-systemd.device-timeout=5s" "nosuid" "nodev" "subvolid=5" ];
    };
    "/home/lam/drives/nixos-old" = {
      device = "/dev/disk/by-uuid/2364de91-8173-4512-b004-1f109b620a55";
      fsType = "ext4";
      options = [ "nofail" "x-systemd.device-timeout=5s" "nosuid" "nodev" ];
    };
    # The 4.5T image-library drive (USB WD Elements; the second of the two,
    # the near-empty one — bak is the other). Previously udisks-mounted as root
    # at a UUID path; declared here so it is present from boot and usable by lam
    # as the canonical cold image archive. Promoted 2026-08-18.
    "/home/lam/drives/img" = {
      device = "/dev/disk/by-uuid/9eff0f0c-d209-4cae-b59d-140ed3b1cf18";
      fsType = "btrfs";
      options = [ "nofail" "x-systemd.device-timeout=10s" "nosuid" "nodev"
                  "subvolid=5" "discard=async" ];
    };
  };

  # own the parent dir so lam can traverse into the mounts
  systemd.tmpfiles.rules = [
    "d /home/lam/drives 0755 lam users - -"
    "d /home/lam/drives/img 0755 lam users - -"
  ];

  # SMART for the disk-hover popup. udisks2 could expose this over D-Bus but
  # the CLI is painful; a NOPASSWD rule is the simple path (quickshell runs as
  # lam, no TTY). Scoped to the fixed-arg `drive-smart` wrapper, not raw
  # smartctl, so the passwordless grant cannot run self-tests or feature toggles.
  security.sudo.extraRules = [{
    users = [ "lam" ];
    commands = [
      { command = "${driveSmart}/bin/drive-smart"; options = [ "NOPASSWD" ]; }
      { command = "${driveLabel}/bin/drive-label"; options = [ "NOPASSWD" ]; }
    ];
  }];

  environment.systemPackages = [ pkgs.smartmontools pkgs.jq driveLabel driveSmart ];
}
