{ pkgs, lib, host, ... }:

{
	home.packages = with pkgs; [
		nicotine-plus
		deluge
		obs-studio
		# yt-dlp is pure-CLI — let nix own it on both hosts.
		yt-dlp
	]
	# The slskd daemon runs on top only: the Soulseek credentials and the
	# library live there, and book reaches it through `slskd-remote`
	# (home/prog/slskd.nix).
	++ lib.optional (host == "top") pkgs.slskd;
}
