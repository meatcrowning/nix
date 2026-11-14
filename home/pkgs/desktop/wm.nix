{ pkgs, lib, host, inputs, ... }:

let
  # The shell comes from the pinned nixpkgs, never the rolling one — see the
  # `nixpkgs-quickshell` input in flake.nix for why. Plain `import` (no
  # overlays, no allowUnfree) because nothing here needs either, and keeping
  # it bare is what makes the evaluation cheap and the store path stable.
  quickshellPinned =
    (import inputs.nixpkgs-quickshell {
      inherit (pkgs.stdenv.hostPlatform) system;
    }).quickshell;
in
{
  home.packages = with pkgs; [
    hyprsunset
    swaybg
    networkmanagerapplet
    pamixer
    cliphist
    # Keep the clipboard alive after the copying app closes (see the
    # `wl-clip-persist --clipboard regular` exec-once in hyprland.lua). Without
    # it a selection owned by a closed client is gone; with it, the persist
    # daemon holds the data so Ctrl+V still works. Both hosts.
    wl-clip-persist
    hyprlauncher
    hyprlang
    hypridle
    kitty
    waybar
    brightnessctl
    ddcutil
    ly
    quickshellPinned
    # screenshots (Screenshot.qml overlay drives grim) + clipboard history
    wl-clipboard
    # screen recording (Screenshot.qml's record mode execs it by bare name):
    # wlroots screencopy grabber, no audio, at the display's refresh rate
    wf-recorder
    ];
}
