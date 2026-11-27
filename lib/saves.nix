# Saves, built from the private `saves` flake input for home/prog/saves.nix.
# top builds it natively; book's is cross-built on top (lib/air-offload.nix),
# which passes the x86 Qt as hostQt and book's Rust target.
{ lib, stdenv, src, root, peer, cmake, cargo, rustc, cargoSetupHook, importCargoLock,
  wrapQtAppsHook, qt6, libglvnd, vulkan-headers, ffmpeg, yt-dlp, gallery-dl, curl,
  coreutils, openssh, hostQt ? null, rustTarget ? null }:
let
  cross = hostQt != null;
in
stdenv.mkDerivation {
  pname = "saves";
  version = "0-${src.shortRev or "dirty"}";
  inherit src;
  cargoDeps = importCargoLock { lockFile = "${src}/Cargo.lock"; };
  nativeBuildInputs = [ cmake cargo rustc cargoSetupHook wrapQtAppsHook ];
  buildInputs = [ qt6.qtbase qt6.qtmultimedia qt6.qtsvg libglvnd vulkan-headers ];
  # CMake runs a plain `cargo build`; cross, cargo targets book and writes
  # the library under the target's triple.
  postPatch = lib.optionalString cross ''
    substituteInPlace CMakeLists.txt --replace-fail cargo/release/ cargo/${rustTarget}/release/
  '';
  env = lib.optionalAttrs cross { CARGO_BUILD_TARGET = rustTarget; };
  # rusqlite bundles SQLite into the static library. cargoSetupHook's
  # system-library default would link it dynamically instead, and the C++
  # link line never names libsqlite3.
  preBuild = "unset LIBSQLITE3_SYS_USE_PKG_CONFIG";
  cmakeFlags = [
    "-DSAVES_ROOT=${root}"
    "-DSAVES_DESKTOP_EXEC=${placeholder "out"}/bin/saves"
  ] ++ lib.optionals cross [
    "-DQT_HOST_PATH=${hostQt}"
    "-DQT_HOST_PATH_CMAKE_DIR=${hostQt}/lib/cmake"
    "-DQt6CoreTools_DIR=${hostQt}/lib/cmake/Qt6CoreTools"
    "-DQt6GuiTools_DIR=${hostQt}/lib/cmake/Qt6GuiTools"
    "-DQt6WidgetsTools_DIR=${hostQt}/lib/cmake/Qt6WidgetsTools"
    "-DQt6DBusTools_DIR=${hostQt}/lib/cmake/Qt6DBusTools"
  ];
  # Suffixed, not prefixed: the profile's pinned yt-dlp and gallery-dl
  # (home/pkgs/media/aquire.nix) carry the site fixes and must win.
  # SAVES_PEER: the other host, which a fetch asks first so the two never
  # download the same posts into the synced library at once.
  qtWrapperArgs = [
    "--suffix PATH : ${lib.makeBinPath [ ffmpeg yt-dlp gallery-dl curl coreutils openssh ]}"
    "--set-default SAVES_PEER ${peer}"
  ];
}
