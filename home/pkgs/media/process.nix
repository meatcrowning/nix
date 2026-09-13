{ pkgs, ... }:

{
	home.packages = with pkgs; [
		ffmpeg
		# metaflac — the shell route to a FLAC tag. `music_tag` is still the
		# way an agent changes a tag (dry run, undo token, ratings left alone);
		# this is the fallback when one is already in a shell, and its absence
		# cost chatter a whole turn on 2026-09-12: it proposed a metaflac
		# command, got exit 127, and spent nine rounds inventing reasons.
		flac
		imagemagick
		picard
		rsgain
		chromaprint
	];
}
