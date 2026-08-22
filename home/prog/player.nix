{ pkgs, lib, host, ... }:

# player — the standalone Qt/QML music player (source at ~/nix/apps/player), fourth
# sibling of surfer/filer/viewer. Packaging mirrors viewer.nix, including the
# air split (air lacks nixpkgs GPU Qt — system python fallback; best-effort
# there, the library SSD hangs off top anyway).
#
# Runtime deps beyond PySide6:
#   * python-mpv (ps.mpv) — libmpv bindings, the playback engine (nixpkgs
#     pre-patches the absolute libmpv path in, so no extra wiring); decodes
#     the whole library incl. DSF/DSD.
#   * mutagen — tag reading for the library scan + FMPS rating/playcount
#     writeback.
#   * mpris-server — exports org.mpris.MediaPlayer2.player so the panel's
#     MediaPanel widget controls this app (pulls pydbus/pygobject).
#
# Runs the LIVE source at ~/nix/apps/player/main.py — .py/.qml edits need no
# rebuild, only dep/packaging changes do.
let
  # ps.pillow: "create systheme" (main.py's createSysthemeFromAlbum) shells
  # out to apps/pylib/systheme.py via sys.executable, i.e. THIS interpreter —
  # without Pillow here the entry point dies with "Pillow is required" on top
  # (book already has it for free: air-launch.sh runs /usr/bin/python3, which
  # dnf's python3-pillow already covers).
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ps.mpv ps.mutagen ps.mpris-server ps.pillow ]);

  # The side-effect-free way to borrow player's Qt environment. Never source the
  # `player` wrapper for it — that runs the BODY (apps/AGENTS.md: surfer's did
  # exactly that and opened three tabs in his live browser). With arguments it
  # execs them inside that environment; with none it prints `export` lines.
  # Same shape as `painter-qtenv` and `surfer-qtenv`, and the harnesses need it:
  # the Plasma face loads the KDE style, the QPA theme and qqc2-desktop-style
  # out of THIS wrapper's plugin path, none of which the raw store python has.
  qtenvBody = pkgs.writeShellScript "player-qtenv-body" ''
    if [ "$#" -eq 0 ]; then
      for v in ''${!QT_@} ''${!QML@} ''${!NIXPKGS_QT@} LOCALE_ARCHIVE PATH; do
        if [ -n "''${!v-}" ]; then printf 'export %s=%q\n' "$v" "''${!v}"; fi
      done
      exit 0
    fi
    exec "$@"
  '';

  player =
    if host == "air" then
      # air plays top's library over SMB, so launching is more than exec'ing
      # python: probe top, mount, pull the metadata database + art cache, run,
      # push back. That lives in the repo as live source (player/tools/
      # air-launch.sh) like everything else here, so it can be fixed on air
      # without a home-manager rebuild — and it degrades to a plain offline
      # launch when top is unreachable. See docs/agents/air-library-share.md.
      pkgs.writeShellScriptBin "player" ''
        exec /home/lam/nix/apps/player/tools/air-launch.sh "$@"
      ''
    else
      pkgs.stdenv.mkDerivation {
        pname = "player";
        version = "live";
        dontUnpack = true;

        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        # qtimageformats adds webp/tiff decoders for embedded/folder cover art
        # beyond qtbase's png/jpg.
        buildInputs = [
          pyEnv
          pkgs.qt6.qtdeclarative
          pkgs.qt6.qtimageformats

          # THE PLASMA FACE (apps/pylib/kdeshell.py). In a Plasma session player
          # is a real QMainWindow — menubar, view toolbar, a transport toolbar
          # along the bottom, a status bar — whose chrome and background are
          # drawn by the KDE style itself. That means the style has to be IN
          # this wrapper's plugin path: it is not enough that the session has
          # it, because a missing plugin here does not fail, it silently leaves
          # the window in Fusion, which is exactly the odd-window-out that face
          # exists to prevent. None of it is loaded in the Hyprland session.
          pkgs.kdePackages.plasma-integration  # the KDE QPA theme: palette,
                                               # fonts, icon theme, widgetStyle
          pkgs.kdePackages.oxygen              # the style + its decoration
          pkgs.kdePackages.breeze              # the default style, as fallback
          pkgs.kdePackages.qqc2-desktop-style  # QQC2 rendered THROUGH QStyle
          pkgs.kdePackages.kirigami            # which qqc2-desktop-style needs
          pkgs.kdePackages.kiconthemes
          pkgs.kdePackages.oxygen-icons        # the icon set the toolbars draw
        ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/player \
            --add-flags /home/lam/nix/apps/player/main.py \
            --prefix XDG_DATA_DIRS : ${lib.concatStringsSep ":" [
              "${pkgs.kdePackages.oxygen-icons}/share"
              "${pkgs.kdePackages.breeze-icons}/share"
            ]} \
            "''${qtWrapperArgs[@]}"

          # Same Qt environment, none of player's body:
          #     player-qtenv python3 apps/player/tools/playbar-test.py
          # air needs no equivalent — there the interpreter IS /usr/bin/python3.
          makeWrapper ${qtenvBody} $out/bin/player-qtenv \
            --prefix PATH : ${pyEnv}/bin \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ player ];

  # App icon: the seal of Amdusias (a duke of the Ars Goetia; his office is to
  # make musical instruments heard), redrawn as clean vector SVG in app-icons/.
  # Installed into the hicolor icon theme so the desktop entry's Icon= AND the
  # titlebar program-icon slot find it (hyprvtb resolves class -> .desktop ->
  # Icon= -> icon theme; a currentColor SVG it tints to the title colour) —
  # same pattern as goetia's seal.
  home.file.".local/share/icons/hicolor/scalable/apps/player.svg".source = ./app-icons/player.svg;
  # …and declare it a SEAL, so the panel paints its currentColor strokes in
  # the focus colour instead of the file's baked fallback (app-icons/seals.nix).
  my.appSeals = [ "player" ];

  # Desktop entry so player shows up in the runner. MPRIS DesktopEntry points
  # here too (the panel widget reads Identity from it).
  #
  # MimeType= is every shared-mime-info type that globs one of the fourteen
  # extensions in player's own AUDIO_EXTS (apps/player/main.py) — keep the two
  # in step, and mirror any change into home/prog/mime-defaults.nix, which is
  # what makes player the *default* rather than merely eligible.
  #
  # `%F` is honoured for real since 2026-07-29: main.py's `paths_from_argv`
  # takes the paths, hands them to a player that is already running over the
  # queue socket's OPEN verb if there is one, and otherwise plays them at
  # startup. Before that it dropped them, which is why this list held nine
  # types and not twenty (docs/agents/mime-defaults-audit.md).
  home.file.".local/share/applications/player.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=player
    GenericName=Music Player
    Comment=Standalone music player for the top desktop
    Exec=${player}/bin/player %F
    Icon=player
    Terminal=false
    Categories=AudioVideo;Audio;Player;
    X-GNOME-UsesNotifications=true
    Keywords=bespoke;
    MimeType=audio/flac;audio/mpeg;audio/mp4;audio/x-m4a;audio/ogg;audio/opus;audio/x-dsf;audio/x-wavpack;audio/x-ape;audio/x-aiff;audio/vnd.wave;audio/x-wav;audio/wav;audio/x-musepack;audio/x-tta;audio/x-dff;audio/x-vorbis+ogg;audio/x-opus+ogg;audio/x-flac+ogg;audio/x-speex+ogg;
  '';
}
