{ ... }:

# book's NixOS root sits in the space macOS used (partition 2). The UUID is set
# at mkfs time so this file could be written before the filesystem existed.
# Fedora's root (partition 6) and its /boot (partition 5) join this btrfs as
# extra devices once Fedora is retired; nothing here changes when that happens.
let
  root = "/dev/disk/by-uuid/79fee31f-ac00-44d8-863a-eb6e9abed62b";
  btrfs = subvol: {
    device = root;
    fsType = "btrfs";
    options = [ "subvol=${subvol}" "compress=zstd" "noatime" ];
  };
in
{
  fileSystems = {
    "/" = btrfs "root";
    "/home" = btrfs "home";
    "/nix" = btrfs "nix";
    # The ESP the Asahi stub boots from, shared with Fedora while both exist.
    "/boot" = {
      device = "/dev/disk/by-partuuid/e5809efa-2e53-4b4f-98cf-b44b52c3d6a7";
      fsType = "vfat";
      options = [ "fmask=0077" "dmask=0077" ];
    };
  };

  boot.initrd.availableKernelModules = [ "usb_storage" ];
}
