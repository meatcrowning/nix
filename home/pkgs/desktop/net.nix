{ pkgs, lib, host, ... }:

let
  # Vivaldi's proprietary H.264/AAC codecs (`vivaldi-ffmpeg-codecs`) and the
  # Widevine CDM (`enableWidevine`) are prebuilt x86_64-only blobs — the codec
  # pkg's src is a hardcoded x86_64 snapcraft snap, and Google ships no desktop
  # aarch64 Widevine — so both fail to build on `air` (Asahi/aarch64) even
  # though their meta.platforms wrongly claims aarch64. Ship them only on
  # x86_64. `air` gets no nix vivaldi at all — see the note below.
  isx86 = pkgs.stdenv.hostPlatform.isx86_64;
in
{
  home.packages = with pkgs; [
	# lynx is a pure-CLI text browser — let nix own it on both hosts.
	lynx
  ] ++ lib.optionals isx86 [
        vivaldi-ffmpeg-codecs
        google-chrome
  # firefox/qutebrowser are GUI browsers with GPU-accelerated rendering
  # (QtWebEngine / gfx): nixpkgs' Mesa lacks Asahi (Honeykrisp) support, so
  # keep them on Fedora's native, hardware-accelerated build on `air`.
  ] ++ lib.optionals (host != "air") [
        qutebrowser
        firefox
        # Vivaldi is nix's on `top` only. On `book` the browser he actually uses
        # is the FLATPAK (com.vivaldi.Vivaldi), whose profile lives in
        # ~/.var/app; the nix build reads ~/.config/vivaldi instead, so its
        # `vivaldi-stable.desktop` in the launcher opened a second, EMPTY
        # profile — which is how a launch from the runner lost him every
        # session cookie he had [2026-08-30]. One install per host, so there is
        # only one profile to land on.
        (vivaldi.override {
          proprietaryCodecs = isx86;
          enableWidevine = isx86;
        })
  ];
}
