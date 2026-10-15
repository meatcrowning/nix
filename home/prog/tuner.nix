{ lib, pkgs, host, ... }:

# tuner — a GTK 3 receiver for top's RTL-SDR dongle (sys/hw/rtl-sdr.nix),
# drawn natively so the Unity session gives it Ambiance Dark and the Ubuntu
# font. Runs the live source at ~/nix/apps/tuner/main.py; see its AGENTS.md.
# top only: the dongle is there, and book reaches it through gqrx-top.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.numpy ps.scipy ps.pygobject3 ps.pycairo ]);
  tuner = pkgs.stdenv.mkDerivation {
    pname = "tuner";
    version = "live";
    dontUnpack = true;
    nativeBuildInputs = [ pkgs.wrapGAppsHook3 pkgs.gobject-introspection pkgs.makeWrapper ];
    buildInputs = [ pkgs.gtk3 pkgs.pango pkgs.gdk-pixbuf pkgs.librsvg ];
    dontWrapGApps = true;
    installPhase = "mkdir -p $out/bin";
    postFixup = ''
      makeWrapper ${pyEnv}/bin/python3 $out/bin/tuner \
        --add-flags /home/lam/nix/apps/tuner/main.py \
        --set TUNER_LIBRTLSDR ${pkgs.rtl-sdr}/lib/librtlsdr.so.0 \
        --prefix PATH : ${lib.makeBinPath [ pkgs.pipewire ]} \
        "''${gappsWrapperArgs[@]}"
    '';
  };
in
lib.mkIf (host == "top") {
  home.packages = [ tuner ];

  xdg.desktopEntries.tuner = {
    name = "Tuner";
    genericName = "Radio Receiver";
    comment = "Listen to FM, weather and other radio through the RTL-SDR dongle";
    exec = "tuner";
    icon = "gqrx";
    categories = [ "AudioVideo" "Audio" "HamRadio" ];
    settings = { StartupWMClass = "tuner"; Keywords = "radio;sdr;fm;rtl;"; };
  };
}
