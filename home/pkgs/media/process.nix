{ pkgs, ... }:

{
	home.packages = with pkgs; [
		ffmpeg
		imagemagick
		picard
		rsgain
		chromaprint
	];
}
