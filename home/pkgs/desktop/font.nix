{ pkgs, ... }:

{
  home.packages = with pkgs; [
    cascadia-code
    source-code-pro
    mononoki
    vista-fonts
    noto-fonts-color-emoji
    oxygenfonts
  ];

  # Not in nixpkgs — quickshell's Theme.qml and kitty.conf both depend on it.
  home.file.".local/share/fonts/MorePerfectDOSVGA.ttf".source =
    ./font-files/MorePerfectDOSVGA.ttf;
}
