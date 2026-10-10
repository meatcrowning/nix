{ pkgs, ... }:
let
  symbola = pkgs.callPackage ../../../lib/quantal-emoji.nix { };
in
{
  # ~/.fonts is visible to both the historical FHS runtime and native apps on
  # top/book. Quantal redirects XDG_DATA_HOME, so modern font installation
  # locations alone are insufficient for its GTK processes.
  home.file.".fonts/Symbola-Quantal.ttf".source = "${symbola}/share/fonts/truetype/Symbola.ttf";
  xdg.configFile."fontconfig/conf.d/52-period-emoji.conf".source = ./font-files/52-period-emoji.conf;
}
