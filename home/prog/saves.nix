{ config, pkgs, lib, inputs, ... }:

# Saves: the Qt gallery for Instagram saves, X bookmarks, YouTube and
# SoundCloud likes, built from the private `saves` flake input. Its library
# root stays the checkout at ~/Projects/saves on both hosts: the gallery-dl
# configs live there and data/ (gitignored) holds the library, which
# saves-sync.nix keeps identical between top and book.
let
  root = "${config.home.homeDirectory}/Projects/saves";
  src = inputs.saves;
  saves = pkgs.stdenv.mkDerivation {
    pname = "saves";
    version = "0-${src.shortRev or "dirty"}";
    inherit src;
    cargoDeps = pkgs.rustPlatform.importCargoLock { lockFile = "${src}/Cargo.lock"; };
    nativeBuildInputs = with pkgs; [
      cmake
      cargo
      rustc
      rustPlatform.cargoSetupHook
      qt6.wrapQtAppsHook
    ];
    buildInputs = with pkgs; [
      qt6.qtbase
      qt6.qtmultimedia
      qt6.qtsvg
      libglvnd
      vulkan-headers
    ];
    # rusqlite bundles SQLite into the static library. cargoSetupHook's
    # system-library default would link it dynamically instead, and the C++
    # link line never names libsqlite3.
    preBuild = "unset LIBSQLITE3_SYS_USE_PKG_CONFIG";
    cmakeFlags = [
      "-DSAVES_ROOT=${root}"
      "-DSAVES_DESKTOP_EXEC=${placeholder "out"}/bin/saves"
    ];
    # Suffixed, not prefixed: the profile's pinned yt-dlp and gallery-dl
    # (home/pkgs/media/aquire.nix) carry the site fixes and must win.
    qtWrapperArgs = [
      "--suffix PATH : ${lib.makeBinPath (with pkgs; [ ffmpeg yt-dlp gallery-dl curl coreutils ])}"
    ];
  };
in
{
  home.packages = [ saves ];
}
