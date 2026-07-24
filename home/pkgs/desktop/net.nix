{ pkgs, lib, host, ... }:

{
  home.packages = with pkgs; [
	  (vivaldi.override {
    proprietaryCodecs = true;
    enableWidevine = true;
  })
	vivaldi-ffmpeg-codecs
	# lynx is a pure-CLI text browser — let nix own it on both hosts.
	lynx
  ] ++ lib.optionals pkgs.stdenv.hostPlatform.isx86_64 [
        google-chrome
  # firefox/qutebrowser are GUI browsers with GPU-accelerated rendering
  # (QtWebEngine / gfx): nixpkgs' Mesa lacks Asahi (Honeykrisp) support, so
  # keep them on Fedora's native, hardware-accelerated build on `air`.
  ] ++ lib.optionals (host != "air") [
        qutebrowser
        firefox
  ];
}
