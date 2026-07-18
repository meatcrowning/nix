{ pkgs, ... }:

{
	home.packages = with pkgs; [
		yt-dlp
		nicotine-plus
		deluge
		obs-studio
		slskd
	];
}
