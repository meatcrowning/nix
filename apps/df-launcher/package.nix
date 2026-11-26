{ stdenv, pkg-config, rustc, glibc, qt6, kdePackages }:

stdenv.mkDerivation {
  pname = "df-launcher";
  version = "1.0";
  src = ./.;

  nativeBuildInputs = [ pkg-config rustc qt6.wrapQtAppsHook ];
  buildInputs = [
    qt6.qtbase qt6.qtwayland
    kdePackages.plasma-integration kdePackages.oxygen kdePackages.breeze
  ];

  buildPhase = ''
    runHook preBuild
    "$CXX" -std=c++17 -O2 -Wall -Wextra main.cpp -o df-launcher $(pkg-config --cflags --libs Qt6Widgets)
    # The capture helper runs inside Steam's runtime, including book's microVM.
    rustc --edition=2021 -O -C target-feature=+crt-static -L native=${glibc.static}/lib capture.rs -o df-launcher-capture
    runHook postBuild
  '';

  dontWrapQtApps = true;
  installPhase = ''
    runHook preInstall
    install -Dm755 df-launcher "$out/bin/df-launcher"
    install -Dm755 df-launcher-capture "$out/bin/df-launcher-capture"
    wrapQtApp "$out/bin/df-launcher" \
      --prefix XDG_DATA_DIRS : "${kdePackages.oxygen-icons}/share:${kdePackages.breeze-icons}/share"
    runHook postInstall
  '';
}
