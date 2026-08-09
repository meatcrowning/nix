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
#   * ffmpeg on PATH — a video family's outputs are clips, and the gallery
#     shows each one's poster frame (extracted once into ~/.cache/painter/
#     posters), plus the muted copy the right-click menu makes. Without it a
#     video tile is blank; on book the wrapper is Fedora's python and ffmpeg
#     comes from its PATH. Putting that copy on the clipboard needs nothing on
#     PATH at all any more — `pylib/clipfile.py` is stdlib-only and owns the
#     selection itself, because wl-copy can offer only one mime type and a file
#     paste needs two (apps/AGENTS.md → pylib).
#   * libnotify on PATH — a generation that finishes behind a rolled-up or
#     unfocused window is announced with a desktop toast carrying its
#     thumbnail, and painter is launched from a .desktop entry / the runner,
#     whose PATH need not carry the profile dirs. book takes Fedora's.
#   * qtmultimedia — the preview viewport plays clips (looped and muted) as well
#     as showing stills, the same QtMultimedia surface viewer uses, including
#     its NVDEC pin: Qt's ffmpeg backend probes VAAPI first and top's VAAPI
#     provider is NVIDIA's shim, which cannot export a surface at all (the whole
#     measurement is in home/prog/viewer.nix). book keeps Qt's default.
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
    if host == "air" then
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
        ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/painter \
            --add-flags /home/lam/nix/apps/painter/main.py \
            --prefix PATH : ${lib.makeBinPath [ pkgs.ffmpeg pkgs.libnotify ]} \
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

  # The inference backend. Started on demand by painter (systemctl --user start),
  # left running afterwards so model weights stay warm.
  systemd.user.services.comfy-painter = lib.mkIf (host != "air") {
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
      ExecStart = pkgs.writeShellScript "comfy-painter-start" ''
        cd ${comfyDir}
        exec nix-shell shell.nix --run '
          exec python main.py \
            --disable-api-nodes \
            --preview-method auto \
            --listen 127.0.0.1 --port 8188 \
            --output-directory "$HOME/Pictures/painter/out" \
            --extra-model-paths-config ${modelsYaml}
        '
      '';
      Restart = "on-failure";
      RestartSec = 3;
      # Model loading is slow; do not let systemd give up on startup.
      TimeoutStartSec = "infinity";

      # No MemoryHigh/MemoryMax here any more. This unit froze `top` on
      # 2026-08-08 — ComfyUI's dynamic VRAM loading stages weights in SYSTEM
      # RAM and streams them to the card, so a MiniMaxH3 video run staged
      # 19995M + 14956M + 2677M against 30G of RAM while kitty, a nix eval and
      # the panel were already swapping, and the box livelocked (reclaiming
      # just fast enough that the kernel OOM killer never fired) rather than
      # crashing outright. The MemoryHigh throttle tried here afterwards
      # (16G, then 20G) fought the wrong problem: it slowed comfy down
      # *before* there was any real pressure, stalling legitimate large loads
      # past painter's startup timeout, without doing anything for the case
      # that actually froze the box — a nixos-rebuild's memory use landing at
      # the same time, entirely outside this cgroup, that no per-unit ceiling
      # here can see.
      # The real fix is `sys/oomd.nix`: systemd-oomd now watches PSI (memory
      # pressure, not allocation failure — the kernel killer's blind spot is
      # exactly the livelock this unit hit) across `user.slice` and kills the
      # worst offender there before the box stops responding, whoever is
      # holding the memory and regardless of which cgroup made it scarce.
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
