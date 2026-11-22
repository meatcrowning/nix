{ pkgs, lib, ... }:

# booru — a booru browser (source at ~/nix/apps/booru), revived from cte's
# Danbooru tab as its own program. Packaging mirrors coder.nix (both faces,
# the KDE style set for Plasma) plus qtmultimedia for posts that are video and
# qtimageformats for webp/avif samples.
#
# It runs the LIVE source, so QML/Python edits need no rebuild.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  qtenvBody = pkgs.writeShellScript "booru-qtenv-body" ''
    if [ "$#" -eq 0 ]; then
      for v in ''${!QT_@} ''${!QML@} ''${!NIXPKGS_QT@} LOCALE_ARCHIVE PATH; do
        if [ -n "''${!v-}" ]; then printf 'export %s=%q\n' "$v" "''${!v}"; fi
      done
      exit 0
    fi
    exec "$@"
  '';

  booru =
      pkgs.stdenv.mkDerivation {
        pname = "booru";
        version = "live";
        dontUnpack = true;
        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        buildInputs = [
          pyEnv
          pkgs.qt6.qtdeclarative
          pkgs.qt6.qtmultimedia
          pkgs.qt6.qtimageformats
          pkgs.qt6.qtsvg
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
          makeWrapper ${pyEnv}/bin/python3 $out/bin/booru \
            --add-flags /home/lam/nix/apps/booru/main.py \
            --prefix XDG_DATA_DIRS : ${lib.concatStringsSep ":" [
              "${pkgs.kdePackages.oxygen-icons}/share"
              "${pkgs.kdePackages.breeze-icons}/share"
            ]} \
            "''${qtWrapperArgs[@]}"
          # Same Qt environment, none of the app:
          #     booru-qtenv python3 apps/booru/tools/booru-test.py
          makeWrapper ${qtenvBody} $out/bin/booru-qtenv \
            --prefix PATH : ${pyEnv}/bin \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ booru ];

  # No MimeType: booru opens no files.
  home.file.".local/share/applications/booru.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=Booru
    GenericName=Booru Browser
    Comment=Search Danbooru and other boorus, read and copy their tags
    Exec=${booru}/bin/booru
    Icon=folder-pictures
    Terminal=false
    Categories=Network;Graphics;
    Keywords=bespoke;danbooru;booru;tags;anime;
  '';
}
