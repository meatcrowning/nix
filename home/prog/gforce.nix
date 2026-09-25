{ pkgs, lib, host, ... }:

# Live frontend and renderer patches travel with nix-pull. The original engine
# stays an upstream dependency, fetched by the rebuild rather than docs sync.
let
  engineArchive = pkgs.fetchurl {
    url = "https://codeload.github.com/Libvisual/libvisual/tar.gz/f14b86f9987ca967491582a603b1cc6e8309626a";
    hash = "sha256-YvCkWo/vG9hbPbXNK5IEgbL64l+V9rwPCca0Vm8EYvk=";
  };
  nativeLibs = pkgs.symlinkJoin {
    name = "gforce-native-libs";
    paths = [ pkgs.libGL pkgs.libGL.dev pkgs.fftwFloat pkgs.fftwFloat.dev ];
  };
  qtenv = pkgs.writeShellScriptBin "gforce-qtenv" ''
    export GF_HOST=${host}
    export GF_ENGINE_ARCHIVE=${engineArchive}
    export GF_PATCH=${pkgs.gnupatch}/bin/patch
    ${if host == "air" then ''
      # Fedora's Python/Qt and graphics ABI stay together on book.
      export PATH=/usr/bin:$PATH
      unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH QML2_IMPORT_PATH LD_LIBRARY_PATH
      export CC=/usr/bin/gcc CXX=/usr/bin/g++
      exec "$@"
    '' else ''
      export PATH=${lib.makeBinPath [ pkgs.pulseaudio pkgs.stdenv.cc ]}:$PATH
      export CC=${pkgs.stdenv.cc}/bin/cc CXX=${pkgs.stdenv.cc}/bin/c++
      export CPATH=${nativeLibs}/include LIBRARY_PATH=${nativeLibs}/lib
      export LD_LIBRARY_PATH=/run/opengl-driver/lib:${nativeLibs}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
      exec player-qtenv "$@"
    ''}
  '';
  gforce = pkgs.writeShellScriptBin "gforce" ''
    exec ${qtenv}/bin/gforce-qtenv python3 /home/lam/nix/apps/gforce/launch.py "$@"
  '';
in
{
  home.packages = [ gforce qtenv ];

  home.file.".local/share/applications/gforce.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=gforce
    GenericName=Music Visualizer
    Comment=Classic iTunes-style visualizer of desktop audio
    Exec=${gforce}/bin/gforce
    Icon=multimedia-audio-player
    Terminal=false
    Categories=AudioVideo;Audio;
    Keywords=visualizer;itunes;g-force;
  '';
}
