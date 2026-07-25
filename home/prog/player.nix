{ pkgs, lib, host, ... }:

# player — the standalone Qt/QML music player (source at ~/nix/player), fourth
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
# Runs the LIVE source at ~/nix/player/main.py — .py/.qml edits need no
# rebuild, only dep/packaging changes do.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ps.mpv ps.mutagen ps.mpris-server ]);

  player =
    if host == "air" then
      pkgs.writeShellScriptBin "player" ''
        exec /usr/bin/python3 /home/lam/nix/player/main.py "$@"
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
            --add-flags /home/lam/nix/player/main.py \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ player ];

  # Desktop entry so player shows up in the runner. MPRIS DesktopEntry points
  # here too (the panel widget reads Identity from it).
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
    MimeType=audio/flac;audio/mpeg;audio/mp4;audio/x-m4a;audio/ogg;audio/opus;audio/x-dsf;audio/x-wavpack;audio/x-ape;
  '';
}
