{ pkgs, lib, host, ... }:

let
  # Vivaldi's proprietary H.264/AAC codecs (`vivaldi-ffmpeg-codecs`) and the
  # Widevine CDM (`enableWidevine`) are prebuilt x86_64-only blobs — the codec
  # pkg's src is a hardcoded x86_64 snapcraft snap, and Google ships no desktop
  # aarch64 Widevine — so both fail to build on `air` (Asahi/aarch64) even
  # though their meta.platforms wrongly claims aarch64. Ship them only on x86_64;
  # `air` gets plain vivaldi (VP9/AV1 play fine; H.264/AAC + DRM don't).
  isx86 = pkgs.stdenv.hostPlatform.isx86_64;
in
{
  home.packages = with pkgs; [
	  (vivaldi.override {
    proprietaryCodecs = isx86;
    enableWidevine = isx86;
  })
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
  ];
}
