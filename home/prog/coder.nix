{ pkgs, lib, hostProfile, ... }:

# coder — a native front end for the claude and codex CLIs (source at
# ~/nix/apps/coder; plan in the private docs/agents/coder-plan.md). It runs the
# CLIs already on PATH and reads their own session stores, so it adds no
# dependency on either one here.
#
#   * air: Fedora's python3 + python3-pyside6, like every app there. A shell
#     started from the Nix-wrapped Konsole carries Nix Qt plugin and QML paths,
#     and Fedora's Qt aborts on them, so the launcher drops them first.
#   * top: nixpkgs' python3 + PySide6 with the KDE style, platform theme and
#     qqc2-desktop-style on the plugin path for the Plasma face (the same set
#     as chatter, apps/AGENTS.md "Plasma chrome and shell").
#
# Both run the LIVE source, so QML/Python edits need no rebuild.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  qtenvBody = pkgs.writeShellScript "coder-qtenv-body" ''
    if [ "$#" -eq 0 ]; then
      for v in ''${!QT_@} ''${!QML@} ''${!NIXPKGS_QT@} LOCALE_ARCHIVE PATH; do
        if [ -n "''${!v-}" ]; then printf 'export %s=%q\n' "$v" "''${!v}"; fi
      done
      exit 0
    fi
    exec "$@"
  '';

  coder =
    if hostProfile.isBook then
      pkgs.writeShellScriptBin "coder" (lib.optionalString hostProfile.isFedora ''
        unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH QML2_IMPORT_PATH \
              QML_IMPORT_PATH NIXPKGS_QT6_QML_IMPORT_PATH LD_LIBRARY_PATH
'' + ''
        exec ${hostProfile.bookPython pkgs} /home/lam/nix/apps/coder/main.py "$@"
      '')
    else
      pkgs.stdenv.mkDerivation {
        pname = "coder";
        version = "live";
        dontUnpack = true;
        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        buildInputs = [
          pyEnv
          pkgs.qt6.qtdeclarative
          pkgs.kdePackages.plasma-integration
          pkgs.kdePackages.oxygen
          pkgs.kdePackages.breeze
          pkgs.kdePackages.qqc2-desktop-style
          pkgs.kdePackages.kirigami
          pkgs.kdePackages.kiconthemes
          pkgs.kdePackages.oxygen-icons
        ];
        dontWrapQtApps = true;
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/coder \
            --add-flags /home/lam/nix/apps/coder/main.py \
            --set-default SPELL_HUNSPELL ${pkgs.hunspell}/bin/hunspell \
            --set-default SPELL_DICPATH ${pkgs.hunspellDicts.en_US}/share/hunspell \
            --prefix XDG_DATA_DIRS : ${lib.concatStringsSep ":" [
              "${pkgs.kdePackages.oxygen-icons}/share"
              "${pkgs.kdePackages.breeze-icons}/share"
            ]} \
            "''${qtWrapperArgs[@]}"
          # Same Qt environment, none of the app:
          #     coder-qtenv python3 apps/coder/main.py --selftest
          makeWrapper ${qtenvBody} $out/bin/coder-qtenv \
            --prefix PATH : ${pyEnv}/bin \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ coder ];

  # No MimeType: coder opens no files.
  home.file.".local/share/applications/coder.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=Coder
    GenericName=Coding Agents
    Comment=Claude Code and Codex sessions
    Exec=${coder}/bin/coder
    Icon=utilities-terminal
    Terminal=false
    Categories=Development;
    Keywords=bespoke;claude;codex;agent;ai;
  '';
}
