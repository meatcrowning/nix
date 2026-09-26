{ pkgs, lib, hostProfile, ... }:

# 4qt — the PySide6 4chan browser at ~/Projects/4qt (its own git repo, top
# only; book has no checkout). It runs that LIVE source, so edits there need no
# rebuild — only changing the runtime deps below does.
#
# The app keeps all of its state relative to the working directory
# (chan_browser.db, chan_browser.log, .cache/, downloads/), so the launcher cds
# into the project before starting it.
let
  dir = "/home/lam/Projects/4qt";

  # Mirrors the project's shell.nix, minus the test-only packages.
  pyEnv = pkgs.python3.withPackages (ps: with ps; [
    pyside6
    httpx
    anyio
    qasync
    curl-cffi
    secretstorage
    cryptography
  ]);

  fourqt = pkgs.stdenv.mkDerivation {
    pname = "4qt";
    version = "live";
    dontUnpack = true;

    nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
    buildInputs = [ pyEnv pkgs.qt6.qtwayland pkgs.qt6.qtmultimedia pkgs.qt6.qtwebengine ];

    dontWrapQtApps = true; # we wrap the python launcher ourselves
    installPhase = ''
      runHook preInstall
      mkdir -p $out/bin
      makeWrapper ${pyEnv}/bin/python3 $out/bin/4qt \
        --chdir ${dir} \
        --add-flags ${dir}/main.py \
        "''${qtWrapperArgs[@]}"
      runHook postInstall
    '';
  };
in
lib.mkIf hostProfile.isTop {
  home.packages = [ fourqt ];

  home.file.".local/share/applications/4qt.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=4qt
    GenericName=Imageboard Browser
    Comment=Browse 4chan boards, threads and media
    Exec=${fourqt}/bin/4qt
    Icon=internet-web-browser
    Terminal=false
    Categories=Network;
    Keywords=4chan;chan;imageboard;
  '';
}
