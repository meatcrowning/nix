{ pkgs, hostProfile, ... }:

# style — live wallpaper and desktop-theme control centre.  Its source stays
# under apps/style and is intentionally run in place: changes to the UI or its
# D-Bus client do not require a rebuild.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);
  style =
    if hostProfile.isBook then
      pkgs.symlinkJoin {
        name = "style-live";
        paths = [
          (pkgs.writeShellScriptBin "style" ''
            exec /usr/bin/python3 /home/lam/nix/apps/style/main.py "$@"
          '')
        ];
      }
    else
      pkgs.stdenv.mkDerivation {
        pname = "style";
        version = "live";
        dontUnpack = true;
        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        buildInputs = [
          pyEnv
          pkgs.qt6.qtdeclarative
          pkgs.kdePackages.qqc2-desktop-style
          pkgs.kdePackages.plasma-integration
          pkgs.kdePackages.oxygen
        ];
        dontWrapQtApps = true;
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/style \
            --add-flags /home/lam/nix/apps/style/main.py \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ style ];
  home.file.".local/share/applications/style.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=style
    GenericName=desktop appearance
    Comment=apply a wallpaper and its live desktop theme
    Exec=${style}/bin/style
    Icon=preferences-desktop-theme-global
    Terminal=false
    Categories=Settings;DesktopSettings;Qt;KDE;
    Keywords=wallpaper;theme;appearance;plasma;oxygen;
  '';
}
