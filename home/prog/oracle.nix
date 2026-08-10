{ pkgs, lib, host, ... }:

# oracle — a minimal chat window for the local ollama daemon (source at
# ~/nix/apps/oracle). A model selector filled from /api/tags and a prompt box
# that streams one turn from /api/chat; nothing else. Packaging mirrors
# board.nix exactly, including the air split:
#
#   * air: nixpkgs' Qt/Mesa can't create a GPU context on Apple Silicon, so
#     exec the SYSTEM python3 with Fedora's python3-pyside6.
#   * top: a plain wrapper over nixpkgs' python3 + PySide6, wrapped with the Qt
#     env. oracle draws only text and talks to a loopback HTTP daemon — no image
#     or media plugins are needed; QtNetwork ships with pyside6.
#
# Both run the LIVE source at ~/nix/apps/oracle/main.py, so QML/Python edits need
# no rebuild — only changing the runtime deps does.
#
# It has no MimeType= and is not a default for anything: oracle is a GUI over a
# daemon, not a file opener (the same reason painter and goetia declare none).
# The desktop entry exists so it is in the runner like the other apps.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  oracle =
    if host == "air" then
      pkgs.writeShellScriptBin "oracle" ''
        exec /usr/bin/python3 /home/lam/nix/apps/oracle/main.py "$@"
      ''
    else
      pkgs.stdenv.mkDerivation {
        pname = "oracle";
        version = "live";
        dontUnpack = true;

        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        buildInputs = [ pyEnv pkgs.qt6.qtdeclarative ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/oracle \
            --add-flags /home/lam/nix/apps/oracle/main.py \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ oracle ];

  home.file.".local/share/applications/oracle.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=oracle
    GenericName=Ollama Chat
    Comment=Chat with the local ollama daemon
    Exec=${oracle}/bin/oracle
    Terminal=false
    Categories=Utility;
    Keywords=ollama;chat;llm;ai;
  '';
}
