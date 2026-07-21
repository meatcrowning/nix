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
  # already native on air (this Fedora install) — skip duplicating there.
  ] ++ lib.optionals (host != "air") [
    gcc
    python3
  ];
}
