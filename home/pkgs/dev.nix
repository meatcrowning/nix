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
    gcc
    # The bare interpreter plus mutagen: a tag read/write in any container,
    # from a plain `python3` on either host. Every repo tool that assumes pure
    # stdlib still runs — a withPackages wrapper is a superset — and the one
    # thing it adds is the fallback an agent reaches for when it is already in
    # a shell and metaflac does not cover the format (m4a, mp3).
    (python3.withPackages (ps: [ ps.mutagen ]))
    cage
  ];
}
