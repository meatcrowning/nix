# Build only the custom ARM leaves with native x86 tools; retain cached ARM libraries.
{ inputs, arm, native }:
let
  hp = inputs.hyprland-air.packages.aarch64-linux.hyprland.overrideAttrs (old: {
    buildInputs = old.buildInputs ++ [ arm.glaze ];
    cmakeFlags = old.cmakeFlags ++ [ "-DCMAKE_INCLUDE_PATH=${arm.glaze}/include" ];
    env = (old.env or {}) // {
      GIT_BRANCH = "unknown"; GIT_COMMIT_DATE = "unknown"; GIT_COMMIT_HASH = "unknown";
      GIT_COMMIT_MESSAGE = "unknown"; GIT_TAG = "unknown";
    };
  });
  headers = hp.overrideAttrs (old: {
    pname = "hyprland-plugin-headers";
    outputs = [ "out" "dev" ];
    buildPhase = ''
      runHook preBuild
      cmake --build . --target generate-protocol-headers -j "$NIX_BUILD_CORES"
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      mkdir -p "$dev/include/hyprland" "$dev/share/pkgconfig" "$out"
      cd ..
      find src protocols -type f \( -name '*.h' -o -name '*.hpp' -o -name '*.inc' \) -exec cp --parents '{}' "$dev/include/hyprland/" \;
      cp build/hyprland.pc "$dev/share/pkgconfig/"
      grep -q '^prefix=' "$dev/share/pkgconfig/hyprland.pc"
      sed -i "s|^prefix=.*|prefix=$dev/include|" "$dev/share/pkgconfig/hyprland.pc"
      runHook postInstall
    '';
    postInstall = "";
    doInstallCheck = false;
  });
  plugin = arm.callPackage ../home/prog/hyprvtb {
    hyprland = headers;
    hyprlandPlugins = arm.hyprlandPlugins.override { hyprland = headers; };
  };
  hpX86 = inputs.hyprland-air.packages.x86_64-linux.hyprland;
  headersX86 = hpX86.overrideAttrs (old: {
    pname = "hyprland-plugin-headers-x86";
    outputs = [ "out" "dev" ];
    inherit (headers.drvAttrs) buildPhase installPhase;
    postInstall = "";
    doInstallCheck = false;
    buildInputs = old.buildInputs ++ [ native.glaze ];
    cmakeFlags = old.cmakeFlags ++ [ "-DCMAKE_INCLUDE_PATH=${native.glaze}/include" ];
    env = (old.env or {}) // {
      GIT_BRANCH = "unknown"; GIT_COMMIT_DATE = "unknown"; GIT_COMMIT_HASH = "unknown";
      GIT_COMMIT_MESSAGE = "unknown"; GIT_TAG = "unknown";
    };
  });
  hpNative = import inputs.hyprland-air.inputs.nixpkgs { system = "x86_64-linux"; };
  crossPlugin = hpNative.pkgsCross.aarch64-multiplatform.gcc16Stdenv.mkDerivation
    ((builtins.removeAttrs plugin.drvAttrs [ "args" "builder" "system" "stdenv" "name" ]) // {
      pname = "hyprvtb-cross";
      buildInputs = map (p: if p == headers.dev then headersX86.dev else p) plugin.buildInputs;
      meta = plugin.meta;
      nativeBuildInputs = [ hpNative.cmake hpNative.pkg-config hpNative.python3 ];
      NIX_CFLAGS_LINK = "";
    });
  hostTools = native.symlinkJoin {
    name = "kf6-cross-host-tools";
    paths = with native.kdePackages; [ kconfig.dev kcoreaddons.dev kdoctools.dev ];
  };
  crossQtWrap = native.qt6.wrapQtAppsHook.override {
    makeBinaryWrapper = native.makeBinaryWrapper.override {
      cc = native.pkgsCross.aarch64-multiplatform.stdenv.cc;
    };
    qtbase = arm.qt6.qtbase;
  };
  crossQt = name:
    let target = arm.kdePackages.${name}; hostPackage = native.kdePackages.${name};
    in native.pkgsCross.aarch64-multiplatform.stdenv.mkDerivation
      ((builtins.removeAttrs target.drvAttrs [ "args" "builder" "system" "stdenv" "name" ]) // {
        pname = "${name}-cross";
        meta = builtins.removeAttrs target.meta [ "mainProgram" ];
        passthru = target.passthru or {};
        outputs = builtins.filter (o: o != "debug") target.outputs;
        nativeBuildInputs = map (p:
          if (p.name or "") == "wrap-qt6-apps-hook" then crossQtWrap else p
        ) hostPackage.nativeBuildInputs ++ [ native.pkg-config native.gettext native.python3 ];
        cmakeFlags = target.cmakeFlags ++ [
          "-DQt6CoreTools_DIR=${native.qt6.qtbase}/lib/cmake/Qt6CoreTools"
          "-DQt6GuiTools_DIR=${native.qt6.qtbase}/lib/cmake/Qt6GuiTools"
          "-DQt6WidgetsTools_DIR=${native.qt6.qtbase}/lib/cmake/Qt6WidgetsTools"
          "-DQt6DBusTools_DIR=${native.qt6.qtbase}/lib/cmake/Qt6DBusTools"
          "-DGETTEXT_MSGFMT_EXECUTABLE=${native.gettext}/bin/msgfmt"
          "-DGETTEXT_MSGMERGE_EXECUTABLE=${native.gettext}/bin/msgmerge"
          "-DKI18N_PYTHON_EXECUTABLE=${native.python3}/bin/python3"
          "-DQT_HOST_PATH=${native.qt6.qtbase}"
          "-DQT_HOST_PATH_CMAKE_DIR=${native.qt6.qtbase}/lib/cmake"
          "-DKF6_HOST_TOOLING=${hostTools}/lib/cmake"
        ];
        doCheck = false;
      });
  crossKonsole = crossQt "konsole";
  oxygenHostTools = native.symlinkJoin {
    name = "oxygen-cross-host-tools";
    paths = [ hostTools native.kdePackages.kcmutils.dev native.kdePackages.kpackage.dev ];
  };
  crossOxygen = (crossQt "oxygen").overrideAttrs (old: {
    outputs = builtins.filter (o: o != "qt5" && o != "debug") old.outputs;
    cmakeFlags = old.cmakeFlags ++ [ "-DBUILD_QT5=OFF" "-DBUILD_QT6=ON" "-DKF6_HOST_TOOLING=${oxygenHostTools}/lib/cmake" ];
    postInstall = "";
  });
in { hyprvtb = crossPlugin; konsole = crossKonsole; oxygen = crossOxygen; headers = headersX86; }
