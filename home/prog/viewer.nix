{ pkgs, lib, host, ... }:

# viewer — the standalone Qt/QML image viewer split out of filer (source at
# ~/nix/viewer). Packaging mirrors filer.nix exactly, including the air split:
#
#   * air: nixpkgs' Qt/Mesa can't create a GPU context on Apple Silicon (no
#     Honeykrisp GBM/EGL driver — same root cause as filer/hyprvtb, see
#     NEXTSTEPS.md), so exec the SYSTEM python3 with Fedora's python3-pyside6.
#   * top: a plain wrapper over nixpkgs' python3 + PySide6, wrapped with the Qt
#     env (qtimageformats/qtsvg add the webp/tiff/svg image plugins beyond
#     qtbase's png/jpg/gif).
#
# Both run the LIVE source at ~/nix/viewer/main.py, so QML/Python edits need no
# rebuild — only changing the runtime deps does. filer opens images by shelling
# out to `viewer <path>` (see filer's openFile), so this must be on PATH.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  viewer =
    if host == "air" then
      pkgs.writeShellScriptBin "viewer" ''
        exec /usr/bin/python3 /home/lam/nix/viewer/main.py "$@"
      ''
    else
      pkgs.stdenv.mkDerivation {
        pname = "viewer";
        version = "live";
        dontUnpack = true;

        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        # qtmultimedia adds the QtMultimedia QML module + its FFmpeg backend so
        # viewer can play videos (the scrub bar / play-pause controls live in the
        # hyprvtb titlebar); qtimageformats/qtsvg add the webp/tiff/svg plugins.
        buildInputs = [ pyEnv pkgs.qt6.qtdeclarative pkgs.qt6.qtimageformats pkgs.qt6.qtsvg pkgs.qt6.qtmultimedia ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/viewer \
            --add-flags /home/lam/nix/viewer/main.py \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ viewer ];

  # Desktop entry so viewer shows up in the runner and can be picked as an image
  # handler. Not forced as the default for image/* (the user's mimeapps.list has
  # its own associations — kate, umpv); filer invokes `viewer` by name directly.
  home.file.".local/share/applications/viewer.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=viewer
    GenericName=Media Viewer
    Comment=Standalone image and video viewer for the top desktop
    Exec=${viewer}/bin/viewer %F
    Icon=image-x-generic
    Terminal=false
    Categories=Graphics;Viewer;AudioVideo;
    MimeType=image/png;image/jpeg;image/gif;image/webp;image/bmp;image/svg+xml;image/avif;image/tiff;video/mp4;video/x-matroska;video/webm;video/quicktime;video/x-msvideo;
  '';
}
