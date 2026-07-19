{ pkgs, ... }:

{
  home.packages = with pkgs; [
    hyprland
    hyprlauncher
    hyprsunset
    hyprpaper
    hyprlang
    hypridle
    kitty
    swaybg
    waybar
    networkmanagerapplet
    brightnessctl
    ddcutil
    pamixer
    ly
    labwc
    quickshell
    noctalia-shell
    # screenshots (Screenshot.qml overlay drives grim) + clipboard history
    wl-clipboard
    cliphist
    ];
}
