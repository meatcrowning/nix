{ pkgs, lib, hostProfile, ... }:

# Painter is the live-source ComfyUI front end under apps/painter. Its wrapper
# supplies WebSockets, multimedia, ffmpeg, libnotify, and hunspell on top; book
# uses Fedora's equivalents. Top pins Qt video decoding away from its broken
# NVIDIA VAAPI export, as documented in viewer.nix.
#
# ComfyUI and the model store remain external mutable state. The on-demand user
# service never starts at boot and keeps warm weights between launches. Python
# and QML edits need only an app relaunch; packaging changes need a rebuild.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  # The side-effect-free way to borrow painter's Qt environment — the harnesses
  # need it, and since the preview viewport pulled in QtMultimedia, the raw
  # store python no longer has the QML modules `tools/ui-test.py` loads. With
  # arguments it execs them inside that environment; with none it prints the
  # variables as `export` lines. Same shape as `surfer-qtenv`, and for the same
  # reason: never source an app's wrapper to get at its env (apps/AGENTS.md).
  qtenvBody = pkgs.writeShellScript "painter-qtenv-body" ''
    if [ "$#" -eq 0 ]; then
      for v in ''${!QT_@} ''${!QML@} ''${!NIXPKGS_QT@} LOCALE_ARCHIVE PATH; do
        if [ -n "''${!v-}" ]; then printf 'export %s=%q\n' "$v" "''${!v}"; fi
      done
      exit 0
    fi
    exec "$@"
  '';

  comfyDir = "/home/lam/comfy";
  modelsYaml = "/home/lam/models/extra_model_paths.yaml";

  painter =
    if hostProfile.isBook then
      # book has no backend of its own — no NVIDIA, no 246G of weights — so it
      # borrows top's, over the ssh forward. The launcher probes top, starts
      # comfy-painter there if it is not already up, waits for it to answer and
      # only then opens the window; unreachable top is fatal with a
      # notification, because a painter that cannot generate is worse than one
      # that did not open. Live source, so it is fixable on book with no
      # home-manager rebuild.
      pkgs.writeShellScriptBin "painter" ''
        exec /home/lam/nix/apps/painter/tools/comfy-tunnel.sh -- \
             /usr/bin/python3 /home/lam/nix/apps/painter/main.py "$@"
      ''
    else
      pkgs.stdenv.mkDerivation {
        pname = "painter";
        version = "live";
        dontUnpack = true;

        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        buildInputs = [
          pyEnv
          pkgs.qt6.qtdeclarative
          pkgs.qt6.qtwebsockets   # ComfyUI progress/event socket
          pkgs.qt6.qtimageformats # webp/tiff alongside qtbase's png/jpg
          pkgs.qt6.qtmultimedia   # the preview viewport's video surface

          # THE PLASMA FACE (apps/pylib/kdeshell.py). In a Plasma session
          # painter is a real QMainWindow whose chrome and background are drawn
          # by the KDE style itself — which means the style has to be IN this
          # wrapper's plugin path. It is not enough that the session has it:
          # a missing plugin here does not fail, it silently leaves the window
          # in Fusion, which is exactly the odd-window-out that face exists to
          # prevent. None of it is loaded in the Hyprland session.
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
          makeWrapper ${pyEnv}/bin/python3 $out/bin/painter \
            --add-flags /home/lam/nix/apps/painter/main.py \
            --prefix PATH : ${lib.makeBinPath [ pkgs.ffmpeg pkgs.libnotify ]} \
            --prefix XDG_DATA_DIRS : ${lib.concatStringsSep ":" [
              "${pkgs.kdePackages.oxygen-icons}/share"
              "${pkgs.kdePackages.breeze-icons}/share"
            ]} \
            --set-default QT_FFMPEG_DECODING_HW_DEVICE_TYPES cuda \
            --set-default SPELL_HUNSPELL ${pkgs.hunspell}/bin/hunspell \
            --set-default SPELL_DICPATH ${pkgs.hunspellDicts.en_US}/share/hunspell \
            "''${qtWrapperArgs[@]}"

          # Same Qt environment, none of painter's body:
          #     painter-qtenv python3 apps/painter/tools/ui-test.py
          # air needs no equivalent — there the interpreter IS /usr/bin/python3.
          makeWrapper ${qtenvBody} $out/bin/painter-qtenv \
            --prefix PATH : ${pyEnv}/bin \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ painter ];

  # Painter's graceful-stop sampler is a Comfy custom node, kept in this repo
  # and linked into the mutable checkout at activation.  The unit is never
  # restarted here: an active generation must finish under the code that began
  # it; the next backend start imports the new node.
  home.activation.painterPartialStopNode = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    if [ -d ${comfyDir}/custom_nodes ]; then
      $DRY_RUN_CMD ln -sfn ${../../apps/painter/comfy_nodes/painter_partial_stop.py} \
        ${comfyDir}/custom_nodes/painter_partial_stop.py
    fi
  '';

  # The inference backend. ai-warden starts it for painter's first renewable
  # client lease and stops it after the last window closes plus a short grace.
  systemd.user.services.comfy-painter = lib.mkIf hostProfile.isTop {
    Unit = {
      Description = "ComfyUI headless inference backend (painter)";
      After = [ "graphical-session.target" ];
      # NEVER RESTARTED BY A REBUILD. This unit holds 8-16G of warm weights and
      # is usually mid-sample; home-manager's default is to restart a changed
      # user service, which would kill a running generation to apply an edit to
      # its own command line. Changes here land at the next start (painter's
      # settings drawer has stop/start).
      X-RestartIfChanged = false;
    };
    Service = {
      Type = "exec";
      WorkingDirectory = comfyDir;
      Environment = [
        "PYTHONNOUSERSITE=1"
        "PYTHONUNBUFFERED=1"
        "PATH=/run/current-system/sw/bin:/run/wrappers/bin"
      ];
      # Two throughput flags, both measured on top's RTX 5070 (sm_120):
      #
      #   --use-sage-attention    SageAttention 2.x, INT8/FP8 attention kernels.
      #     NOT a pip dependency of ComfyUI and NOT reinstalled by shell.nix:
      #     it is built from source into ${comfyDir}/.venv, and a fresh venv
      #     comes back WITHOUT it (the backend then refuses to start on this
      #     flag). Rebuild it the way `docs/agents/comfy-sageattention.md`
      #     records — nvcc must be CUDA 13.0 to match torch's cu130, which the
      #     24.11 pin in shell.nix does not have, so the toolkit comes from the
      #     system channel's `cudaPackages_13_0`.
      #   --fast fp16_accumulation  fp16 matmuls accumulate in fp16 rather than
      #     fp32. The other three `--fast` features are deliberately NOT on:
      #     fp8_matrix_mult and cublas_ops trade image quality, and autotune's
      #     cudnn.benchmark only pays off at a fixed resolution, which painter
      #     is not.
      ExecStart = pkgs.writeShellScript "comfy-painter-start" ''
        cd ${comfyDir}
        exec nix-shell shell.nix --run '
          exec python main.py \
            --disable-api-nodes \
            --preview-method auto \
            --use-sage-attention \
            --fast fp16_accumulation \
            --listen 127.0.0.1 --port 8188 \
            --output-directory "$HOME/Pictures/painter/out" \
            --extra-model-paths-config ${modelsYaml}
        '
      '';
      Restart = "on-failure";
      RestartSec = 3;
      # Model loading is slow; do not let systemd give up on startup.
      TimeoutStartSec = "infinity";

      # Do not add MemoryHigh/MemoryMax: ComfyUI legitimately stages large
      # weights in system RAM, and per-unit throttling cannot see a concurrent
      # rebuild. sys/oomd.nix instead watches PSI across user.slice and kills
      # the worst offender before reclaim livelocks the machine.
    };
    # No Install section: never auto-started at boot.
  };

  # App icon: the planetary seal of Venus (beauty, art), redrawn as clean
  # vector SVG in app-icons/. Installed into the hicolor icon theme so the
  # desktop entry's Icon= AND the titlebar program-icon slot find it (hyprvtb
  # resolves class -> .desktop -> Icon= -> icon theme; a currentColor SVG it
  # tints to the title colour) — same pattern as goetia's seal.
  home.file.".local/share/icons/hicolor/scalable/apps/painter.svg".source = ./app-icons/painter.svg;
  # …and declare it a SEAL, so the panel paints its currentColor strokes in
  # the focus colour instead of the file's baked fallback (app-icons/seals.nix).
  my.appSeals = [ "painter" ];

  home.file.".local/share/applications/painter.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=painter
    GenericName=Image Generation
    Comment=Text-to-image front end for a local ComfyUI
    Exec=${painter}/bin/painter
    Icon=painter
    Terminal=false
    Categories=Graphics;2DGraphics;
    X-GNOME-UsesNotifications=true
    Keywords=bespoke;
  '';
}
