{ pkgs, ... }:

{
  home.file.".local/share/icons/hicolor/scalable/actions/launcher-circle.svg".source =
    ./app-icons/launcher-circle.svg;

  # Breeze's 22px symbol has a 3px inset on every side. On the narrow left
  # panel that leaves only 16px of visible artwork. Crop the SVG canvas so
  # the same theme-coloured logo fills the launcher's available icon area.
  home.file.".local/share/icons/hicolor/scalable/places/launcher-kde-symbolic.svg".source =
    pkgs.runCommand "launcher-kde-symbolic.svg" { } ''
      substitute ${pkgs.kdePackages.breeze-icons}/share/icons/breeze/places/22/start-here-kde-symbolic.svg $out \
        --replace-fail 'viewBox="0 0 22 22"' 'viewBox="3 3 16 16"'
    '';
}
