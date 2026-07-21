{ pkgs, lib, host, ... }:

{
  home.packages = with pkgs; [
	  (vivaldi.override {
    proprietaryCodecs = true;
    enableWidevine = true;
  })
	vivaldi-ffmpeg-codecs
  ] ++ lib.optionals pkgs.stdenv.hostPlatform.isx86_64 [
        google-chrome
  # already native on air (this Fedora install) — skip duplicating there.
  ] ++ lib.optionals (host != "air") [
	lynx
        qutebrowser
        firefox
  ];
}
