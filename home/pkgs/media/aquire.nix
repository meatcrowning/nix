{ pkgs, lib, host, ... }:

{
	home.packages = with pkgs; [
		nicotine-plus
		deluge
		obs-studio
		slskd
	# already native on air (this Fedora install) — skip duplicating there.
	] ++ lib.optionals (host != "air") [
		yt-dlp
	];
}
