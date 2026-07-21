{pkgs, lib, host, ... }:

{
	home.packages = with pkgs; [
		vlc
		kew
		# do i really need media server shit like actually though
		# jellyfin-desktop
		# plex-desktop
		# jellyfin
		# jellyfin-web
		# jellyfin-ffmpeg
	] ++ lib.optionals pkgs.stdenv.hostPlatform.isx86_64 [
		spotify
	# already native on air (this Fedora install) — skip duplicating there.
	] ++ lib.optionals (host != "air") [
		mpv
	# no cached aarch64-linux build, compiles from source (slow) — skip on
	# air for now, add back if wanted.
	] ++ lib.optionals (host == "top") [
		fooyin
	];
}
