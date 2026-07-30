{ pkgs, lib, host, ... }:

# painter — text-to-image front end for a headless ComfyUI (source at
# ~/nix/apps/painter), fifth sibling of surfer/filer/viewer/player. Packaging mirrors
# player.nix, including the air split.
#
# Two things differ from the other siblings:
#
#   * qtwebsockets — the ComfyUI client listens on /ws for progress, node
#     transitions, errors and live previews, instead of polling /history the way
#     cte did.
#   * a systemd --user unit for the backend. ComfyUI is NOT packaged here: it
#     stays the venv+nix-shell checkout at /home/lam/comfy (a symlink to
#     Downloads/git/ComfyUI), whose shell.nix already handles the hard parts
#     (nixpkgs-24.11 pin, torch cu128, patchelfing Triton's ptxas for NixOS).
#     The unit is started on demand by the app and deliberately NOT stopped on
#     exit, so 8-16G of weights stay resident between launches. No wantedBy, so
#     it never starts at boot.
#
# Models live at /home/lam/models (~246G, the consolidated root shared with cte
# via a symlink) and are reached through extra_model_paths.yaml. None of that is
# in this repo.
#
# Runs the LIVE source at ~/nix/apps/painter/main.py — .py/.qml edits need no
# rebuild, only dep/packaging changes do.
#
# The prompt boxes are spellchecked (`pylib/spellcheck.py`), which talks to the
# `hunspell` BINARY in pipe mode rather than to a Python binding — so the two
# `SPELL_*` variables below are the whole wiring, and **book's branch gets
# nothing**: there the checker resolves `hunspell` from `$PATH` and
# `/usr/share/hunspell`, and marks nothing at all if Fedora has neither. See
# `home/prog/editor.nix` for the same note at length.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  comfyDir = "/home/lam/comfy";
  modelsYaml = "/home/lam/models/extra_model_paths.yaml";

  painter =
    if host == "air" then
      pkgs.writeShellScriptBin "painter" ''
        exec /usr/bin/python3 /home/lam/nix/apps/painter/main.py "$@"
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
        ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/painter \
            --add-flags /home/lam/nix/apps/painter/main.py \
            --set-default SPELL_HUNSPELL ${pkgs.hunspell}/bin/hunspell \
            --set-default SPELL_DICPATH ${pkgs.hunspellDicts.en_US}/share/hunspell \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ painter ];

  # The inference backend. Started on demand by painter (systemctl --user start),
  # left running afterwards so model weights stay warm.
  systemd.user.services.comfy-painter = lib.mkIf (host != "air") {
    Unit = {
      Description = "ComfyUI headless inference backend (painter)";
      After = [ "graphical-session.target" ];
    };
    Service = {
      Type = "exec";
      WorkingDirectory = comfyDir;
      Environment = [
        "PYTHONNOUSERSITE=1"
        "PYTHONUNBUFFERED=1"
        "PATH=/run/current-system/sw/bin:/run/wrappers/bin"
      ];
      ExecStart = pkgs.writeShellScript "comfy-painter-start" ''
        cd ${comfyDir}
        exec nix-shell shell.nix --run '
          exec python main.py \
            --disable-api-nodes \
            --listen 127.0.0.1 --port 8188 \
            --output-directory "$HOME/Pictures/painter/out" \
            --extra-model-paths-config ${modelsYaml}
        '
      '';
      Restart = "on-failure";
      RestartSec = 3;
      # Model loading is slow; do not let systemd give up on startup.
      TimeoutStartSec = "infinity";
    };
    # No Install section: never auto-started at boot.
  };

  home.file.".local/share/applications/painter.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=painter
    GenericName=Image Generation
    Comment=Text-to-image front end for a local ComfyUI
    Exec=${painter}/bin/painter
    Icon=applications-graphics
    Terminal=false
    Categories=Graphics;2DGraphics;
    Keywords=bespoke;
  '';
}
