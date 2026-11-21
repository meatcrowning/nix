{pkgs, lib, host, config, ... }:

{
	# VLC asks for credentials before trying SSH keys when the URL has no user.
	# Keep its preferences writable, but supply the local login as the default.
	home.activation.vlcSftpUser = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
		${pkgs.python3}/bin/python3 ${./vlc-sftp-user.py} \
			"${config.xdg.configHome}/vlc/vlcrc" "${config.home.username}"
	'';

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
		mpv
	# no cached aarch64-linux build, compiles from source (slow) — skip on
	# air for now, add back if wanted.
	] ++ lib.optionals (host == "top") [
		fooyin
	];
}
