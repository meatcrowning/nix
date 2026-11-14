{ ... }:

# book's root is one btrfs over two partitions: 2 (where macOS was) and 5
# (where Fedora's /boot and root were). The UUID was set at mkfs time.
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
    # The ESP the Asahi stub boots from: m1n1 stage 2, vendor firmware, loaders.
    "/boot" = {
      device = "/dev/disk/by-partuuid/e5809efa-2e53-4b4f-98cf-b44b52c3d6a7";
      fsType = "vfat";
      options = [ "fmask=0077" "dmask=0077" ];
    };
  };

  boot.initrd.availableKernelModules = [ "usb_storage" ];
}
