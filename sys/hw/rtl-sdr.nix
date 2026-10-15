{ pkgs, user, ... }:

let
  # UHD's USRP broadcast discovery intermittently deadlocks in boost::asio
  # inside gqrx's MainWindow constructor, so no window ever appears. It is
  # reached directly and through Soapy's soapyuhd module; gqrx drives the
  # dongle with osmosdr's native rtl source, so build without both.
  osmosdrNoUhd = pkgs.gnuradioMinimal.pkgs.osmosdr.override {
    features = { uhd = false; soapy = false; };
  };
  gqrx = pkgs.gqrx.overrideAttrs (old: {
    buildInputs = map (p: if (p.pname or "") == "gr-osmosdr" then osmosdrNoUhd else p) old.buildInputs;
  });
in
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
    gqrx         # simpler tuning GUI (UHD-free, above)
    (callPackage ../../lib/ais-catcher.nix { })  # ship AIS, web map
  ];
}
