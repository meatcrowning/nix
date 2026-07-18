{ pkgs, ... }:

{
  home.packages = with pkgs; [
    cmake
    gcc
    gnumake
    python3
    (dotnetCorePackages.combinePackages [ dotnet-sdk dotnetCorePackages.runtime_10_0-bin ])
    #nodePackages.npm
    nodejs
    rustc
    cargo
  ];
}
