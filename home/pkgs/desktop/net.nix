{ pkgs, ... }:

{
  home.packages = with pkgs; [
	lynx    
	  (vivaldi.override {
    proprietaryCodecs = true;
    enableWidevine = true;
  })
	vivaldi-ffmpeg-codecs
        google-chrome
        qutebrowser
        firefox
  ];
}
