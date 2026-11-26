{ pkgs, lib, host, ... }:

{
	home.packages = with pkgs; [
		nicotine-plus
		deluge
		obs-studio
		# yt-dlp is pure-CLI — let nix own it on both hosts. Pinned ahead of
		# nixpkgs for YouTube's player-change fixes (2026.11.23: n-challenge).
		(yt-dlp.overridePythonAttrs (final: prev: {
			version = "2026.11.23";
			src = pkgs.fetchFromGitHub {
				owner = "yt-dlp";
				repo = "yt-dlp";
				tag = final.version;
				hash = "sha256-BpxnzY9GOs9sTv/ZWAwYiiJS7VfaMtp5HHOtXDAGgc0=";
			};
		}))
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
