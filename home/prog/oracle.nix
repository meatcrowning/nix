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
#
# On air, ollama is top's — loopback-pinned there (sys/ai/ollama.nix) same as
# painter's ComfyUI, so it is reached the identical way: an ssh port forward,
# never a new listener (root AGENTS.md → "Off-LAN: the tailnet"). The launcher
# is apps/oracle/tools/ollama-tunnel.sh, modelled on painter's
# comfy-tunnel.sh; oracle's OLLAMA env var defaults to 127.0.0.1:11434, so with
# the forward up it needs no further configuration.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  oracle =
    if host == "air" then
      pkgs.writeShellScriptBin "oracle" ''
        exec /home/lam/nix/apps/oracle/tools/ollama-tunnel.sh -- \
             /usr/bin/python3 /home/lam/nix/apps/oracle/main.py "$@"
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

  # App icon: the seal of Gusion (an eleventh-spirit duke of the Ars Goetia;
  # his office is to discern all things past, present and to come and to resolve
  # all questions asked of him), redrawn as clean vector SVG in app-icons/ —
  # the seal of a divination window. Installed into the hicolor icon theme so
  # the desktop entry's Icon= AND the titlebar program-icon slot find it
  # (hyprvtb resolves class -> .desktop -> Icon= -> icon theme; a currentColor
  # SVG it tints to the title colour) — same pattern as player's seal.
  home.file.".local/share/icons/hicolor/scalable/apps/oracle.svg".source = ./app-icons/oracle.svg;
  # …and declare it a SEAL, so the panel paints its currentColor strokes in the
  # focus colour instead of the file's baked fallback (app-icons/seals.nix).
  my.appSeals = [ "oracle" ];

  home.file.".local/share/applications/oracle.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=chatter
    GenericName=Ollama Chat
    Comment=Chat with the local ollama daemon
    Exec=${oracle}/bin/oracle
    Icon=oracle
    Terminal=false
    Categories=Utility;
    Keywords=bespoke;ollama;chat;llm;ai;
  '';
}
