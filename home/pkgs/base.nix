{ pkgs, kde-material-you-colors-latest, ... }:

{
  home.packages = with pkgs; [
    vim
    btop
    tree
    unzip
    git
    gh
    nh
    wget
    curl
    rsync
    htop
    fastfetch
    broot
    cmatrix
    croc
    libnotify
    home-manager
    feh
    cava
    killall
    open-webui
    playerctl
    smartmontools
    usbutils
    btrfs-progs
    claude-code
    ranger

    #kde-material-you-colors-latest
    #ventoy-full-qt
    #kquitapp6
    #okay maybe a little media
  ];
}
