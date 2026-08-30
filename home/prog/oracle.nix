{ pkgs, lib, host, ... }:

# oracle — a minimal chat window for the local ollama daemon (source at
# ~/nix/apps/oracle). A model selector filled from /api/tags and a prompt box
# that streams one turn from /api/chat; nothing else. Packaging mirrors
# board.nix exactly, including the air split:
#
#   * air: nixpkgs' Qt/Mesa can't create a GPU context on Apple Silicon, so
#     exec the SYSTEM python3 with Fedora's python3-pyside6.
#   * top: a plain wrapper over nixpkgs' python3 + PySide6, wrapped with the Qt
#     env. Beyond QtNetwork (which ships with pyside6) it needs qtmultimedia:
#     `show_video` plays a video inline in a reply, and the QML MediaPlayer +
#     its FFmpeg backend live in that module. yt-dlp is on PATH for the same
#     tool — it is what turns a YouTube (or other) watch page into the stream
#     URL the player pulls; without it only a DIRECT video file URL resolves,
#     which the tool then says (docs/DESIGN.md §10). playerctl is the other
#     binary on that PATH: `control_player` drives the music player over MPRIS
#     through it, because PySide cannot demarshal MPRIS's `a{sv}` Metadata
#     (apps/oracle/AGENTS.md — the title came back empty).
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

  # The side-effect-free way to borrow chatter's Qt environment. Never source
  # the `oracle` wrapper for it — that runs the BODY (apps/AGENTS.md: surfer's
  # did exactly that and opened three tabs in his live browser). With arguments
  # it execs them inside that environment; with none it prints `export` lines.
  # Same shape as `player-qtenv` and `painter-qtenv`, and the harness needs it:
  # the Plasma face loads the KDE style, the QPA theme and qqc2-desktop-style
  # out of THIS wrapper's plugin path, none of which the raw store python has.
  qtenvBody = pkgs.writeShellScript "oracle-qtenv-body" ''
    if [ "$#" -eq 0 ]; then
      for v in ''${!QT_@} ''${!QML@} ''${!NIXPKGS_QT@} LOCALE_ARCHIVE PATH; do
        if [ -n "''${!v-}" ]; then printf 'export %s=%q\n' "$v" "''${!v}"; fi
      done
      exit 0
    fi
    exec "$@"
  '';

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
        buildInputs = [
          pyEnv
          pkgs.qt6.qtdeclarative
          pkgs.qt6.qtmultimedia   # MediaPlayer/VideoOutput for show_video

          # THE PLASMA FACE (apps/pylib/kdeshell.py). In a Plasma session
          # chatter is a real QMainWindow — menubar, a toolbar carrying the
          # model and session pickers, a status bar — whose chrome and
          # background are drawn by the KDE style itself. That means the style
          # has to be IN this wrapper's plugin path: it is not enough that the
          # session has it, because a missing plugin here does not fail, it
          # silently leaves the window in Fusion, which is exactly the
          # odd-window-out that face exists to prevent. None of it is loaded in
          # the Hyprland session.
          pkgs.kdePackages.plasma-integration  # the KDE QPA theme: palette,
                                               # fonts, icon theme, widgetStyle
          pkgs.kdePackages.oxygen              # the style + its decoration
          pkgs.kdePackages.breeze              # the default style, as fallback
          pkgs.kdePackages.qqc2-desktop-style  # QQC2 rendered THROUGH QStyle
          pkgs.kdePackages.kirigami            # which qqc2-desktop-style needs
          pkgs.kdePackages.kiconthemes
          pkgs.kdePackages.oxygen-icons        # the icon set the toolbar draws
        ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/oracle \
            --add-flags /home/lam/nix/apps/oracle/main.py \
            --prefix PATH : ${lib.makeBinPath [ pkgs.yt-dlp pkgs.playerctl ]} \
            --set-default QT_FFMPEG_DECODING_HW_DEVICE_TYPES cuda \
            --prefix XDG_DATA_DIRS : ${lib.concatStringsSep ":" [
              "${pkgs.kdePackages.oxygen-icons}/share"
              "${pkgs.kdePackages.breeze-icons}/share"
            ]} \
            "''${qtWrapperArgs[@]}"

          # Same Qt environment, none of chatter's body:
          #     oracle-qtenv python3 apps/oracle/main.py --selftest
          makeWrapper ${qtenvBody} $out/bin/oracle-qtenv \
            --prefix PATH : ${pyEnv}/bin \
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
