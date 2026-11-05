{ pkgs, lib, host, ... }:

{
	home.packages = with pkgs; [
		nicotine-plus
		deluge
		obs-studio
		# yt-dlp is pure-CLI — let nix own it on both hosts.
		yt-dlp
		# Keep extractor fixes current until the nixpkgs pin catches up.
		(gallery-dl.overrideAttrs (final: prev: {
			version = "1.32.19";
			src = pkgs.fetchFromCodeberg {
				owner = "mikf";
				repo = "gallery-dl";
				tag = "v${final.version}";
				hash = "sha256-iMC0KpgyYPqyHpYwYw9DFsvCMHUIwqqVP2Pfm1SviB0=";
			};
			meta = prev.meta // {
				changelog = "https://codeberg.org/mikf/gallery-dl/src/tag/v${final.version}/CHANGELOG.md";
			};
		}))
	]
	++ lib.optional (host == "top") pkgs.slskd;
}
