{ pkgs, lib, host, ... }:

# goetia — what needs him, what is moving, what landed (source at ~/nix/apps/board).
#
# The PROGRAM is called Goetia (lowercase `goetia` in every string it draws, like
# every other app here). Only the presentation was renamed: the store it reads and
# writes is still `docs/board.<hostname>.md` — one board per host since
# 2026-07-30 — and every path, module and identifier is still
# `board*` — this file, `apps/board/`, `boardctl.py`, `board-watch`. His call.
# Packaging mirrors reader.nix exactly, including the air split:
#
#   * air: nixpkgs' Qt/Mesa can't create a GPU context on Apple Silicon (no
#     Honeykrisp GBM/EGL driver — same root cause as filer/viewer/reader, see
#     docs/agents/air-port-nextsteps.md), so exec the SYSTEM python3 with
#     Fedora's python3-pyside6.
#   * top: a plain wrapper over nixpkgs' python3 + PySide6, wrapped with the Qt
#     env. goetia draws only text — no image or media plugins are needed.
#
# Both run the LIVE source at ~/nix/apps/board/main.py, so QML/Python edits need
# no rebuild — only changing the runtime deps does.
#
# It has no MimeType= and is not a default for anything: goetia is a GUI over ONE
# file (~/nix/docs/board.<hostname>.md, this machine's own board), not a markdown viewer — that is `reader`, which
# goetia opens the same file in from its `md` titlebar cell. The desktop entry
# exists so it is in the runner like the other seven.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  goetia =
    if host == "air" then
      pkgs.writeShellScriptBin "goetia" ''
        exec /usr/bin/python3 /home/lam/nix/apps/board/main.py "$@"
      ''
    else
      pkgs.stdenv.mkDerivation {
        pname = "goetia";
        version = "live";
        dontUnpack = true;

        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        buildInputs = [ pyEnv pkgs.qt6.qtdeclarative ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/goetia \
            --add-flags /home/lam/nix/apps/board/main.py \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ goetia ];

  home.file.".local/share/applications/board.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=goetia
    GenericName=Decision Board
    Comment=What needs you, what is moving, what landed
    Exec=${goetia}/bin/goetia
    Icon=text-x-generic
    Terminal=false
    Categories=Utility;
    Keywords=bespoke;goetia;board;decisions;
  '';
}
