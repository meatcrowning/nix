{ pkgs, ... }:

{
  home.packages = with pkgs; [
    gimp
    libreoffice-qt-fresh
    qdirstat
    terminator
    wineWow64Packages.staging
    ];
}
