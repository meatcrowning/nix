{ pkgs, lib, host, ... }:

# filer — the standalone Qt/QML file browser split out of the Quickshell panel
# (source at ~/nix/filer, in this repo so it travels to every machine on pull).
# This module:
#   * builds a fast-launching `filer` wrapper binary (task: instant cold start),
#   * registers its desktop entry so it appears in the Quickshell runner, and
#   * makes it the default handler for directories (task: default file manager).
#
# INSTANT COLD START: the wrapper is a plain store binary — `python3` (with
# PySide6) + Qt env baked in by wrapQtAppsHook — so launching it is just an
# exec, with none of the ~1s `nix develop` evaluation the old run.sh launcher
# paid every time. It still runs the LIVE source at ~/nix/filer/main.py
# (not a baked copy), so day-to-day QML/Python edits need no rebuild — only
# changing the runtime deps (PySide6, Qt) does. The absolute path resolves on
# both `top` and `air` (book), since ~/nix lives at /home/lam/nix on each.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  # On air, nixpkgs' Qt/Mesa can't get a GPU context: same root cause already
  # diagnosed for hyprvtb/Hyprland in NEXTSTEPS.md — nixpkgs' Mesa has no
  # working Apple Silicon (Honeykrisp) GBM/EGL driver, so QRhiGles2 fails to
  # create a context and the app aborts. Fedora's own Mesa (system) does have
  # it — it's what quickshell/Hyprland already run against here — so on air,
  # skip nixpkgs' Qt/PySide6 entirely and exec the system python3 with the
  # dnf-installed python3-pyside6 instead. `top` is untouched.
  filer =
    if host == "air" then
      pkgs.writeShellScriptBin "filer" ''
        exec /usr/bin/python3 /home/lam/nix/filer/main.py "$@"
      ''
    else
      pkgs.stdenv.mkDerivation {
        pname = "filer";
        version = "live";
        dontUnpack = true;

        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        buildInputs = [ pyEnv pkgs.qt6.qtdeclarative ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/filer \
            --add-flags /home/lam/nix/filer/main.py \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ filer ];

  # Desktop entry (written via home.file since xdg.enable is off here — see the
  # note that used to live in this file / commit history). Exec is the absolute
  # store path so it resolves regardless of the launcher's PATH; it regenerates
  # on each rebuild. MimeType marks it as a directory handler.
  home.file.".local/share/applications/filer.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=filer
    GenericName=File Browser
    Comment=Standalone file browser for the top desktop
    Exec=${filer}/bin/filer
    Icon=system-file-manager
    Terminal=false
    Categories=Utility;System;FileTools;
    MimeType=inode/directory;
  '';

  # Default application for opening directories → filer.
  #
  # Done via xdg-mime (not xdg.mimeApps) on purpose: a real ~/.config/mimeapps.list
  # already exists with the user's own associations (kate, umpv, …), and letting
  # home-manager take the file over would either refuse (clobber error) or, with
  # force, discard those. `xdg-mime default` edits the [Default Applications]
  # section in place — adding just inode/directory — and leaves everything else
  # untouched. Idempotent, so it's safe to re-run on every switch.
  home.activation.filerDefaultFileManager =
    lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      run ${pkgs.xdg-utils}/bin/xdg-mime default filer.desktop inode/directory
    '';
}
