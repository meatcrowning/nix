{
  description = "viewer — standalone Qt/QML image viewer for the top desktop";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});
    in
    {
      packages = forAll (pkgs: {
        default = pkgs.stdenv.mkDerivation {
          pname = "viewer";
          version = "0.1.0";
          src = ./.;

          nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
          buildInputs = [ (pkgs.python3.withPackages (ps: [ ps.pyside6 ])) pkgs.qt6.qtdeclarative pkgs.qt6.qtimageformats pkgs.qt6.qtsvg pkgs.qt6.qtmultimedia ];

          dontWrapQtApps = true; # we wrap the python launcher ourselves, below
          installPhase = ''
            runHook preInstall
            mkdir -p $out/share/viewer $out/bin
            cp main.py $out/share/viewer/
            cp -r qml $out/share/viewer/
            makeWrapper ${pkgs.python3.withPackages (ps: [ ps.pyside6 ])}/bin/python3 \
              $out/bin/viewer \
              --add-flags "$out/share/viewer/main.py" \
              ''${qtWrapperArgs[@]}
            runHook postInstall
          '';
        };
      });

      apps = forAll (pkgs: {
        default = {
          type = "app";
          program = "${self.packages.${pkgs.system}.default}/bin/viewer";
        };
      });

      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: [ ps.pyside6 ]))
            pkgs.qt6.qtdeclarative
            pkgs.qt6.qtimageformats
            pkgs.qt6.qtsvg
            pkgs.qt6.qtmultimedia
          ];
        };
      });
    };
}
