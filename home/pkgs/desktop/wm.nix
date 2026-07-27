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
    # screen recording (Screenshot.qml overlay drives wf-recorder in record
    # mode) — lightweight wlroots screencopy grabber, no audio, matches the
    # display refresh rate
    wf-recorder
    ];
}
