{ pkgs, ... }:

# Touchpad kinetic scrolling for book's KWin (source: home/prog/kwin-momentum,
# runbook: docs/agents/kwin-momentum-plugin-runbook.md). Built against the same
# nixpkgs KWin the session runs, and installed on the system Qt plugin path.
# It ships disabled (metadata EnabledByDefault=false); turning it on is the
# user's step: kwriteconfig6 --file kwinrc --group Plugins
#   --key kwin_momentumEnabled true, then a new Plasma login.
let
  src = ../../home/prog/kwin-momentum;
  kwinMomentum = pkgs.stdenv.mkDerivation {
    pname = "kwin-momentum";
    version = "0.1.0";
    inherit src;
    sourceRoot = "kwin-momentum/src";
    unpackPhase = ''
      cp -r ${src} kwin-momentum
      chmod -R u+w kwin-momentum
    '';
    nativeBuildInputs = with pkgs; [ cmake kdePackages.extra-cmake-modules ];
    buildInputs = with pkgs.kdePackages; [ kwin qtbase qtdeclarative ];
    dontWrapQtApps = true;
    doCheck = true;
    checkPhase = ''
      # cwd is src/build; the engine test needs no KWin headers.
      $CXX -std=c++20 -I .. ../../test/momentum-engine-test.cpp \
        ../momentumengine.cpp -o momentum-engine-test
      ./momentum-engine-test
    '';
    installPhase = ''
      install -Dm755 bin/kwin_momentum.so \
        $out/lib/qt-6/plugins/kwin/plugins/kwin_momentum.so
    '';
  };
in
{
  environment.systemPackages = [ kwinMomentum ];
}
