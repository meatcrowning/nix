{ pkgs, user, ... }:

{
  # RTL2832U dongle (0bda:2838, R820T tuner). hardware.rtl-sdr blacklists the
  # kernel DVB-T driver, which otherwise claims the device and makes librtlsdr
  # fail with "usb_claim_interface error -6", and adds udev rules for plugdev.
  hardware.rtl-sdr = {
    enable = true;
    package = pkgs.rtl-sdr; # rtl-sdr-blog fork: also drives the V3/V4 dongles
  };
  users.users.${user}.extraGroups = [ "plugdev" ];

  environment.systemPackages = with pkgs; [
    sdrpp        # waterfall/tuning GUI
    rtl_433      # 315/433/915 MHz sensors, meters, TPMS
    dump1090-fa  # ADS-B 1090 MHz
    gqrx         # simpler tuning GUI
    (callPackage ../../lib/ais-catcher.nix { })  # ship AIS, web map
  ];
}
