{ pkgs, lib, host, ... }:

# board — what needs him, what is moving, what landed (source at ~/nix/apps/board).
# Packaging mirrors reader.nix exactly, including the air split:
#
#   * air: nixpkgs' Qt/Mesa can't create a GPU context on Apple Silicon (no
#     Honeykrisp GBM/EGL driver — same root cause as filer/viewer/reader, see
#     docs/agents/air-port-nextsteps.md), so exec the SYSTEM python3 with
#     Fedora's python3-pyside6.
#   * top: a plain wrapper over nixpkgs' python3 + PySide6, wrapped with the Qt
#     env. board draws only text — no image or media plugins are needed.
#
# Both run the LIVE source at ~/nix/apps/board/main.py, so QML/Python edits need
# no rebuild — only changing the runtime deps does.
#
# It has no MimeType= and is not a default for anything: board is a GUI over ONE
# file (~/nix/docs/board.md), not a markdown viewer — that is `reader`, which
# board opens the same file in from its `md` titlebar cell. The desktop entry
# exists so it is in the runner like the other seven.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  board =
    if host == "air" then
      pkgs.writeShellScriptBin "board" ''
        exec /usr/bin/python3 /home/lam/nix/apps/board/main.py "$@"
      ''
    else
      pkgs.stdenv.mkDerivation {
        pname = "board";
        version = "live";
        dontUnpack = true;

        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        buildInputs = [ pyEnv pkgs.qt6.qtdeclarative ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/board \
            --add-flags /home/lam/nix/apps/board/main.py \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ board ];

  home.file.".local/share/applications/board.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=board
    GenericName=Decision Board
    Comment=What needs you, what is moving, what landed
    Exec=${board}/bin/board
    Icon=text-x-generic
    Terminal=false
    Categories=Utility;
    Keywords=bespoke;board;decisions;
  '';
}
