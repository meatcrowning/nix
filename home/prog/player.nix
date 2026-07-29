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
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ps.mpv ps.mutagen ps.mpris-server ]);

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
        buildInputs = [ pyEnv pkgs.qt6.qtdeclarative pkgs.qt6.qtimageformats ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/player \
            --add-flags /home/lam/nix/apps/player/main.py \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ player ];

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
    Icon=audio-x-generic
    Terminal=false
    Categories=AudioVideo;Audio;Player;
    Keywords=bespoke;
    MimeType=audio/flac;audio/mpeg;audio/mp4;audio/x-m4a;audio/ogg;audio/opus;audio/x-dsf;audio/x-wavpack;audio/x-ape;audio/x-aiff;audio/vnd.wave;audio/x-wav;audio/wav;audio/x-musepack;audio/x-tta;audio/x-dff;audio/x-vorbis+ogg;audio/x-opus+ogg;audio/x-flac+ogg;audio/x-speex+ogg;
  '';
}
