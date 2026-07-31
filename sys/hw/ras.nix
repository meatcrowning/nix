{ pkgs, ... }:

{
  # Hardware-error monitoring on `top`. Added 2026-07-30 while chasing silent
  # single-byte corruption in /nix/store .drv files (docs/agents/nix-store-bitrot-hardware.md).
  #
  # The investigation found every error counter on the machine at zero — and
  # also found that *nothing was watching any of them*. Two real gaps:
  #
  #   1. No smartd. A growing NVMe media-error count would have gone unnoticed
  #      indefinitely; the drive holding / and /nix is the whole system.
  #   2. Hardware-error history was ~6 days long. services.journald is capped
  #      at SystemMaxUse=500M (sys/base.nix) and nothing persisted machine
  #      checks or PCIe AER events past it, on a box with 3,270 power-on hours.
  #
  # What this CANNOT give: memory errors. These are non-ECC DDR5 UDIMMs, so
  # `amd64_edac` refuses to bind ("No such device"), /sys/devices/system/edac/mc
  # is empty and SMBIOS reports Error Correction Type: None. DDR5's on-die ECC
  # corrects inside the DRAM array and reports nothing to the host. A DRAM or
  # DIMM-link bit error here is silent by construction and no daemon changes
  # that. Do not read "rasdaemon reports no memory errors" as "there are none".
  #
  # NixOS-only, so `book` gets none of this.

  # Persists MCEs and PCIe AER events to /var/lib/rasdaemon/ras-mc_event.db,
  # which survives reboots and journal rotation. Read with `ras-mc-ctl --errors`
  # / `--summary`. Baseline at install: 0 machine-check exceptions on all 16
  # threads, 0 AER events.
  hardware.rasdaemon.enable = true;

  services.smartd = {
    enable = true;

    # Explicit list, not DEVICESCAN. The three USB drives are deliberately
    # absent: `arc`'s bridge exposes no SMART at all (docs/top-storage-tiers.md
    # §1), and the other two are `nofail` mounts that may simply not be plugged
    # in — smartd refuses to start on a device it cannot open, so autodetect
    # would make a missing drive a failed boot service. Check those by hand:
    #   sudo -n "$(readlink -f "$(command -v smartctl)")" -a -d sat,12 /dev/sdX
    autodetect = false;

    # Named by /dev/disk/by-id — kernel sd* letters are NOT stable here; two
    # drives swapped letters twice in one day (see sys/disks.nix).
    devices = [
      # The NVMe holding / and /nix/store. WD Green SN3000 2TB.
      { device = "/dev/disk/by-id/nvme-WD_Green_SN3000_2TB_25174Y801133"; }
      # cld — internal SATA HDD, btrfs data drive.
      { device = "/dev/disk/by-id/ata-WDC_WD10EZEX-00BN5A0_WD-WCC3F2RH1K2K";
        options = "-a -n standby,q"; }
      # linux-old — internal SATA HDD, old generic-Linux root.
      { device = "/dev/disk/by-id/ata-HGST_HTS725050A7E630_TF1500WHKLLLNM";
        options = "-a -n standby,q"; }
      # nixos-old — internal SATA SSD, previous NixOS install.
      { device = "/dev/disk/by-id/ata-PNY_CS900_120GB_SSD_PNY224822112801002C6"; }
    ];

    # `-n standby,q` above keeps smartd from spinning the HDDs up just to poll
    # them. The module default for `monitored` is a bare `-a`: health, failing
    # attributes, error-log growth, pending and uncorrectable sectors — and
    # deliberately NO scheduled self-tests and no `-W` temperature thresholds,
    # which would fire constantly (the NVMe's controller-die sensor idles at
    # ~73 C, well inside its 89.8 C spec).

    # A drive going bad must actually reach him. Wall only fires on a real
    # SMART failure, not on routine polling.
    notifications.wall.enable = true;
  };

  # Establishing the trained memory speed (EXPO vs JEDEC) meant reaching into
  # /nix/store by hash because this was not installed. It is the only way to
  # read SMBIOS type 17.
  environment.systemPackages = [ pkgs.dmidecode ];
}
