{ pkgs, lib, host, ... }:

{
  home.packages = with pkgs; [
    #nodePackages.npm
    nodejs
    # The bare interpreter plus mutagen: a tag read/write in any container,
    # from a plain `python3` on either host. Every repo tool that assumes pure
    # stdlib still runs — a withPackages wrapper is a superset — and the one
    # thing it adds is the fallback an agent reaches for when it is already in
    # a shell and metaflac does not cover the format (m4a, mp3).
    (python3.withPackages (ps: [ ps.mutagen ]))
    cage
  ] ++ lib.optionals (host == "top") [
    # Book already has Fedora's native C/C++/Rust tools. Keep the full Nix
    # development toolchains on top; use a task-specific shell when needed
    # on book instead of retaining another SDK in every home generation.
    cmake
    gnumake
    (dotnetCorePackages.combinePackages [ dotnet-sdk dotnetCorePackages.runtime_10_0-bin ])
    rustc
    cargo
    gcc
  ];
}
