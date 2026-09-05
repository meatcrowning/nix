{ pkgs, lib, hostProfile, ... }:

# viewer — the standalone Qt/QML image viewer split out of filer (source at
# ~/nix/apps/viewer). Packaging mirrors filer.nix exactly, including the air split:
#
#   * air: nixpkgs' Qt/Mesa can't create a GPU context on Apple Silicon (no
#     Honeykrisp GBM/EGL driver — same root cause as filer/hyprvtb, see
#     docs/agents/air-port-nextsteps.md), so exec the SYSTEM python3 with Fedora's python3-pyside6.
#   * top: a plain wrapper over nixpkgs' python3 + PySide6, wrapped with the Qt
#     env (qtimageformats/qtsvg add the webp/tiff/svg image plugins beyond
#     qtbase's png/jpg/gif).
#
# Both run the LIVE source at ~/nix/apps/viewer/main.py, so QML/Python edits need no
# rebuild — only changing the runtime deps does. filer opens images by shelling
# out to `viewer <path>` (see filer's openFile), so this must be on PATH.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  viewer =
    if hostProfile.isBook then
      pkgs.writeShellScriptBin "viewer" ''
        exec /usr/bin/python3 /home/lam/nix/apps/viewer/main.py "$@"
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
        #
        # NVDEC, NEVER VAAPI (this branch is `top`, i.e. the NVIDIA box). Qt's
        # ffmpeg backend probes hw decoders in its own order and picks VAAPI
        # first; the VAAPI provider on `top`'s default render node
        # (/dev/dri/renderD128) is NVIDIA's own shim, nvidia_drv_video.so, and it
        # cannot export a surface as a DRM-prime handle at all — measured on the
        # sandbox monitor 2026-08-05, `vaExportSurfaceHandle failed` 202x in 9s
        # for a VP9 clip and 392x for a VP8 one, i.e. EVERY frame. Qt then falls
        # back to a per-frame CPU transfer, which is both why video played badly
        # and how viewer died: av_hwframe_transfer_data -> vaapi_transfer_data_from
        # -> av_image_copy asserts on a plane-size mismatch and abort()s, which is
        # both viewer coredumps on `top` (2026-07-30 and 2026-08-03, a .webm each).
        # `cuda` is real NVDEC and logs zero export failures on the same clips;
        # Qt falls back to software on its own for anything NVDEC cannot decode,
        # so this narrows the choice rather than forcing it. --set-default, so
        # `QT_FFMPEG_DECODING_HW_DEVICE_TYPES= viewer x.webm` still bisects it by
        # hand. book is not NVIDIA and keeps Qt's default (the `air` branch above
        # has no wrapper to set it in).
        buildInputs = [ pyEnv pkgs.qt6.qtdeclarative pkgs.qt6.qtimageformats pkgs.qt6.qtsvg pkgs.qt6.qtmultimedia ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/viewer \
            --add-flags /home/lam/nix/apps/viewer/main.py \
            --set-default QT_FFMPEG_DECODING_HW_DEVICE_TYPES cuda \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ viewer ];

  # App icon: the planetary seal of Sol (the sun), redrawn as clean vector SVG
  # in app-icons/. Installed into the hicolor icon theme so the desktop entry's
  # Icon= AND the titlebar program-icon slot find it (hyprvtb resolves class ->
  # .desktop -> Icon= -> icon theme; a currentColor SVG it tints to the title
  # colour) — same pattern as goetia's seal.
  home.file.".local/share/icons/hicolor/scalable/apps/viewer.svg".source = ./app-icons/viewer.svg;
  # …and declare it a SEAL, so the panel paints its currentColor strokes in
  # the focus colour instead of the file's baked fallback (app-icons/seals.nix).
  my.appSeals = [ "viewer" ];

  # Desktop entry so viewer shows up in the runner and is eligible for image and
  # video types. Being the DEFAULT for them is set centrally, in
  # home/prog/mime-defaults.nix. (filer invokes `viewer` by name directly and
  # does not go through the MIME database at all.)
  #
  # MimeType mirrors viewer's IMAGE_EXTS + VIDEO_EXTS (apps/viewer/main.py) —
  # keep the three in sync. Video really is played, through QtMultimedia's
  # ffmpeg backend, with the transport controls in the hyprvtb titlebar.
  home.file.".local/share/applications/viewer.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=viewer
    GenericName=Media Viewer
    Comment=Standalone image and video viewer for the top desktop
    Exec=${viewer}/bin/viewer %F
    Icon=viewer
    Terminal=false
    Categories=Graphics;Viewer;AudioVideo;
    Keywords=bespoke;
    MimeType=image/png;image/jpeg;image/gif;image/webp;image/bmp;image/svg+xml;image/avif;image/jxl;image/tiff;image/x-icon;image/vnd.microsoft.icon;image/x-portable-pixmap;image/x-portable-graymap;video/mp4;video/x-matroska;video/webm;video/quicktime;video/x-msvideo;video/mpeg;video/x-ms-wmv;video/x-flv;video/mp2t;video/ogg;video/3gpp;
  '';
}
