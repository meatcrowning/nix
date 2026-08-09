{ pkgs, lib, host, ... }:

# updater — the desktop's GUI for this flake's package updates (source at
# ~/nix/apps/updater). It checks for updates by shelling out to the read-only
# preview `tools/nix-upgradable.sh`, updates non-pinned inputs (or one input)
# with `nix flake update`, and rebuilds through this host's own wrapper.
#
# Packaging mirrors reader.nix — the plain live-source wrapper with the air
# split, no extra runtime deps (it draws text and runs subprocesses):
#
#   * air (book): exec the SYSTEM python3 with Fedora's python3-pyside6, same
#     reason as reader/viewer (nixpkgs Qt/Mesa can't make a GPU context on
#     Apple Silicon).
#   * top: a plain wrapper over nixpkgs' python3 + PySide6, wrapped with the Qt
#     env.
#
# Both run the LIVE source at ~/nix/apps/updater/main.py, so Python/QML edits
# need no rebuild — only changing the runtime deps or this file does.
#
# The subprocesses it runs (`nix`, `nix-upgradable.sh`, and the rebuild wrapper
# — `sudo rebuild-top` on top, `rebuild-air` on book) are resolved from the
# session PATH, not pinned here: they are the user's own live tools and the
# rebuild wrapper is host-specific by construction.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  updater =
    if host == "air" then
      pkgs.writeShellScriptBin "updater" ''
        exec /usr/bin/python3 /home/lam/nix/apps/updater/main.py "$@"
      ''
    else
      pkgs.stdenv.mkDerivation {
        pname = "updater";
        version = "live";
        dontUnpack = true;

        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        buildInputs = [ pyEnv pkgs.qt6.qtdeclarative ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/updater \
            --add-flags /home/lam/nix/apps/updater/main.py \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ updater ];

  # App icon: a redrawn refresh glyph in currentColor SVG, installed into the
  # hicolor icon theme so both the desktop entry's Icon= and the titlebar
  # program-icon slot find it. Declared a SEAL so the panel paints its
  # currentColor strokes in the focus colour (app-icons/seals.nix).
  home.file.".local/share/icons/hicolor/scalable/apps/updater.svg".source = ./app-icons/updater.svg;
  my.appSeals = [ "updater" ];

  # No MimeType=: like painter and goetia, updater has no honest file to open —
  # it is a GUI over the flake, so it declares no association (apps/AGENTS.md).
  home.file.".local/share/applications/updater.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=updater
    GenericName=Package Updater
    Comment=Check for and apply this flake's package updates
    Exec=${updater}/bin/updater
    Icon=updater
    Terminal=false
    Categories=System;Settings;
    Keywords=bespoke;nix;flake;update;upgrade;packages;
  '';
}
