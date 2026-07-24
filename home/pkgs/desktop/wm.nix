{ pkgs, lib, host, inputs, ... }:

{
  home.packages = with pkgs; [
    hyprsunset
    swaybg
    networkmanagerapplet
    pamixer
    cliphist
  # already native on air (this Fedora install, including the Hyprland this
  # very session is running under) — skip duplicating there. Tried swapping
  # air to nixpkgs' own hyprland as the actual compositor instead (so
  # hyprvtb could match hashes without the override below) — it crashed on
  # startup: nixpkgs' Mesa lacks working Apple Silicon (Honeykrisp GBM)
  # driver support that Fedora Asahi's patched Mesa has (aquamarine got past
  # DRM/KMS enumeration fine, then failed creating a GBM allocator). Not
  # fixable without nixGL-style host-Mesa injection, which isn't set up and
  # is its own can of worms — reverted, back to the GIT_*-forced-unknown
  # hyprvtb build below.
  ] ++ lib.optionals (host != "air") [
    hyprlauncher
    # hyprpaper from the hyprwm flake, not nixpkgs' crash-prone 0.8.4 — see
    # the `hyprpaper` input in flake.nix.
    inputs.hyprpaper.packages.${pkgs.stdenv.hostPlatform.system}.hyprpaper
    hyprlang
    hypridle
    kitty
    waybar
    brightnessctl
    ddcutil
    ly
    quickshell
    # screenshots (Screenshot.qml overlay drives grim) + clipboard history
    wl-clipboard
    # screen recording (Screenshot.qml overlay drives wf-recorder in record
    # mode) — lightweight wlroots screencopy grabber, no audio, matches the
    # display refresh rate
    wf-recorder
    ];
}
