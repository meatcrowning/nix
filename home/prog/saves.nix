{ config, pkgs, inputs, host, airOffload ? null, ... }:

# Saves: the Qt gallery for Instagram saves, X bookmarks, YouTube and
# SoundCloud likes, built from the private `saves` flake input. Its library
# root stays the checkout at ~/Projects/saves on both hosts: the gallery-dl
# configs live there and data/ (gitignored) holds the library, which
# saves-sync.nix keeps identical between top and book.
let
  root = "${config.home.homeDirectory}/Projects/saves";
  peer = if host == "top" then "book" else "top";
  saves =
    if host == "air" then airOffload.saves { inherit root peer; }
    else pkgs.callPackage ../../lib/saves.nix {
      inherit root peer;
      src = inputs.saves;
      inherit (pkgs.rustPlatform) cargoSetupHook importCargoLock;
      inherit (pkgs.qt6) wrapQtAppsHook;
    };
in
{
  home.packages = [ saves ];
}
