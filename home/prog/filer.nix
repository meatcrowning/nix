{ pkgs, lib, host, ... }:

# filer — the standalone Qt/QML file browser split out of the Quickshell panel
# (source at ~/nix/apps/filer, in this repo so it travels to every machine on pull).
# This module:
#   * builds a fast-launching `filer` wrapper binary (task: instant cold start),
#   * registers its desktop entry so it appears in the Quickshell runner, and
#   * declares it a directory handler (being the DEFAULT one is set centrally,
#     in home/prog/mime-defaults.nix).
#
# INSTANT COLD START: the wrapper is a plain store binary — `python3` (with
# PySide6) + Qt env baked in by wrapQtAppsHook — so launching it is just an
# exec, with none of the ~1s `nix develop` evaluation the old run.sh launcher
# paid every time. It still runs the LIVE source at ~/nix/apps/filer/main.py
# (not a baked copy), so day-to-day QML/Python edits need no rebuild — only
# changing the runtime deps (PySide6, Qt) does. The absolute path resolves on
# both `top` and `air` (book), since ~/nix lives at /home/lam/nix on each.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  # On air, nixpkgs' Qt/Mesa can't get a GPU context: same root cause already
  # diagnosed for hyprvtb/Hyprland in docs/agents/air-port-nextsteps.md — nixpkgs' Mesa has no
  # working Apple Silicon (Honeykrisp) GBM/EGL driver, so QRhiGles2 fails to
  # create a context and the app aborts. Fedora's own Mesa (system) does have
  # it — it's what quickshell/Hyprland already run against here — so on air,
  # skip nixpkgs' Qt/PySide6 entirely and exec the system python3 with the
  # dnf-installed python3-pyside6 instead. `top` is untouched.
  filer =
    if host == "air" then
      pkgs.writeShellScriptBin "filer" ''
        # Same `mimetype` prefix as the `top` wrapper below, and book is the
        # host that actually needs it: `home.packages` puts it in
        # ~/.nix-profile/bin, which the graphical session's PATH does not
        # contain here (measured on book 2026-07-29: Hyprland's own PATH is
        # /usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin).
        export PATH="${pkgs.perlPackages.FileMimeInfo}/bin:$PATH"
        exec /usr/bin/python3 /home/lam/nix/apps/filer/main.py "$@"
      ''
    else
      pkgs.stdenv.mkDerivation {
        pname = "filer";
        version = "live";
        dontUnpack = true;

        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        # qtimageformats/qtsvg add the extra image plugins (webp, tiff, svg, …)
        # the built-in viewer decodes beyond qtbase's png/jpg/gif — wrapQtAppsHook
        # puts them on QT_PLUGIN_PATH. (On `air` filer runs Fedora's system Qt,
        # which already ships these, so this only matters for `top`.)
        buildInputs = [ pyEnv pkgs.qt6.qtdeclarative pkgs.qt6.qtimageformats pkgs.qt6.qtsvg ];

        # glib gives filer `gio`, which is what BOTH "trash" actions shell out
        # to — and it was on no PATH the app could ever see (not the session's,
        # not the nix profile's, not /run/current-system/sw/bin). Trash was
        # therefore a perfect silent no-op for its whole life: the selection
        # cleared, the list refreshed, the files stayed. It went unnoticed
        # because FileOps.run reported success unconditionally; it is visible
        # now (a "cannot run gio" toast), and this makes it work instead.
        # book gets /usr/bin/gio from Fedora's glib2 and needs nothing.

        # sshfs is what the address bar's `:host` syntax mounts with
        # (apps/filer/remote.py). It is here rather than in home.packages for
        # the same reason gio is: the app inherits no profile bin dir when the
        # runner or a .desktop entry launches it. book needs nothing added —
        # it runs Fedora's python3 with /usr/sbin on PATH, and nixpkgs' sshfs
        # would be the wrong one there anyway (its libfuse looks for the setuid
        # fusermount3 in /run/wrappers/bin, which only exists on NixOS).

        # File-MimeInfo gives `mimetype`, and this is the ONLY way it reaches
        # the one caller that matters. Opening a non-image shells out to
        # `xdg-open`, whose generic branch asks `xdg-mime query filetype`,
        # whose `info_generic()` runs `mimetype` if it is on PATH and
        # `file --mime-type` otherwise — and `file` reads content, so every
        # glob-only type (.md, .svg, .csv) resolved to text/plain and the
        # defaults in mime-defaults.nix were never consulted for it.
        # `home.packages` there is not enough: it lands in a profile bin dir
        # that this app inherits only when it was launched from a shell.


        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/filer \
            --add-flags /home/lam/nix/apps/filer/main.py \
            --prefix PATH : ${lib.makeBinPath [ pkgs.glib pkgs.perlPackages.FileMimeInfo pkgs.sshfs ]} \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ filer ];

  # App icon: the seal of Vine (a king of the Ars Goetia, its tree figure),
  # redrawn as clean vector SVG in app-icons/. Installed into the hicolor icon
  # theme so the desktop entry's Icon= AND the titlebar program-icon slot
  # (hyprvtb resolves class -> .desktop -> Icon= -> icon theme; a currentColor
  # SVG it tints to the title colour) find it — same pattern as goetia's seal.
  home.file.".local/share/icons/hicolor/scalable/apps/filer.svg".source = ./app-icons/filer.svg;
  # …and declare it a SEAL, so the panel paints its currentColor strokes in
  # the focus colour instead of the file's baked fallback (app-icons/seals.nix).
  my.appSeals = [ "filer" ];

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
    Exec=${filer}/bin/filer %f
    Icon=filer
    Terminal=false
    Categories=Utility;System;FileTools;
    X-GNOME-UsesNotifications=true
    Keywords=bespoke;
    MimeType=inode/directory;
  '';

  # Making filer the DEFAULT directory handler (rather than merely an eligible
  # one) now lives in home/prog/mime-defaults.nix, alongside viewer's and
  # surfer's — one list of "what opens what" instead of three activation
  # snippets racing for the same file. It used to be an `xdg-mime default` call
  # here; see that file for why it no longer is.
}
