{ pkgs, lib, host, ... }:

{
	home.packages = with pkgs; [
		nicotine-plus
		deluge
		obs-studio
		# yt-dlp is pure-CLI — let nix own it on both hosts.
		yt-dlp
	]
	++ lib.optional (host == "top") pkgs.slskd;
}
