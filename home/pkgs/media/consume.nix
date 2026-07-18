{pkgs, ... }:

{
	home.packages = with pkgs; [
		spotify
		mpv
		vlc
		kew
		fooyin
		# do i really need media server shit like actually though
		# jellyfin-desktop
		# plex-desktop
		# jellyfin
		# jellyfin-web
		# jellyfin-ffmpeg
	];
}
