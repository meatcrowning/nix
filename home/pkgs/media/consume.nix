{pkgs, lib, host, ... }:

{
	# Let Dolphin use KIO/FUSE's authenticated connection for remote files.
	# VLC's native SFTP/SMB clients otherwise prompt independently of KIO.
	xdg.dataFile."applications/vlc.desktop".source = pkgs.runCommand "vlc-kio-desktop" {} ''
		cp ${pkgs.vlc}/share/applications/vlc.desktop "$out"
		chmod u+w "$out"
		substituteInPlace "$out" \
			--replace-fail 'X-KDE-Protocols=ftp,http,https,mms,rtmp,rtsp,sftp,smb' \
			'X-KDE-Protocols=ftp,http,https,mms,rtmp,rtsp'
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
