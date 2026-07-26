{ pkgs, lib, host, ... }:

{
  home.packages = with pkgs; [
    cmake
    gnumake
    (dotnetCorePackages.combinePackages [ dotnet-sdk dotnetCorePackages.runtime_10_0-bin ])
    #nodePackages.npm
    nodejs
    rustc
    cargo
    # Let nix own the toolchain on both hosts too (was gated off air to avoid
    # duplicating Fedora's copies — no real reason to keep it on dnf).
    gcc
    python3
    # Headless parent compositor for tools/sandbox.sh — a wlroots kiosk that,
    # with WLR_BACKENDS=headless, provides a Wayland display rendering to
    # nowhere. That is what lets a test session (nested Hyprland + hyprvtb, GUI
    # apps) run entirely off-screen instead of popping windows into the live
    # desktop. See tools/sandbox.sh and AGENTS.md.
    cage
  ];
}
