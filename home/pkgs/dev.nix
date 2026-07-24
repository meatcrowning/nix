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
  ];
}
