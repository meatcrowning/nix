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
    paths = [ hostTools ] ++ (with native.kdePackages; [ kcmutils.dev kpackage.dev kauth.dev ]);
  };
  crossOxygen = (crossQt "oxygen").overrideAttrs (old: {
    buildInputs = (old.buildInputs or []) ++ [ arm.kdePackages.kiconthemes ];
    # Book's applications and KWin decoration load THIS Oxygen. Same patch set
    # and order as Fedora's native build had: themed Vivaldi frames, native
    # content (from the overlay), the maximised-window field, compact menus.
    patches = [ ../home/prog/oxygen-themed-vivaldi.patch ] ++ (old.patches or [])
      ++ [ ../home/prog/oxygen-desktop-field.patch ../home/prog/oxygen-compact-menus.patch ];
    outputs = builtins.filter (o: o != "qt5" && o != "debug") old.outputs;
    cmakeFlags = old.cmakeFlags ++ [ "-DBUILD_QT5=OFF" "-DBUILD_QT6=ON" "-DKF6_HOST_TOOLING=${oxygenHostTools}/lib/cmake" ];
    postInstall = "";
  });
  # replaceDependencies (lib/plasma-tooltip-padding.nix) needs the same
  # store-name length as book's package, but cross builds always append the
  # target triple. Copy the build under the native name and rewrite its own
  # path, padded with slashes to keep every string the same length.
  nativeNamed = name: drv: native.runCommand "${name}-${arm.kdePackages.${name}.version}"
    { nativeBuildInputs = [ native.perl ]; } ''
    cp -a ${drv} $out
    chmod -R u+w $out
    old=$(basename ${drv}) new=$(basename $out)
    pad=$(printf "%''${#old}s" "" | cut -c$((''${#new} + 1))- | tr ' ' /)
    find $out -type f -print0 | xargs -0 perl -0777 -pi -e "s|\Q$old\E(?!-)|$new$pad|g"
    find $out -type l | while read -r l; do
      t=$(readlink "$l"); ln -sfn "''${t//$old/$new}" "$l"
    done
    if grep -rqP "\Q$old\E(?!-)" $out; then echo "stale $old reference" >&2; exit 1; fi
  '';
  intltoolMerge = native.writeShellScript "intltool-merge" ''
    PERL5LIB=${native.perlPackages.makePerlPath [ native.perlPackages.XMLParser ]} \
      exec ${native.intltool}/bin/intltool-merge "$@"
  '';
  crossPatched = name: patch: nativeNamed name ((crossQt name).overrideAttrs (old: {
    patches = (old.patches or []) ++ [ patch ];
    cmakeFlags = old.cmakeFlags ++ [
      "-DKF6_HOST_TOOLING=${oxygenHostTools}/lib/cmake"
      "-DWaylandScanner_EXECUTABLE=${native.wayland-scanner.bin}/bin/wayland-scanner"
      "-DQt6QmlTools_DIR=${native.qt6.qtdeclarative}/lib/cmake/Qt6QmlTools"
      "-DQt6QuickTools_DIR=${native.qt6.qtdeclarative}/lib/cmake/Qt6QuickTools"
      "-DINTLTOOL_MERGE=${intltoolMerge}"
      "-DQt6ShaderToolsTools_DIR=${native.qt6.qtshadertools}/lib/cmake/Qt6ShaderToolsTools"
    ];
    doInstallCheck = false;
  }));
  crossLibplasma = crossPatched "libplasma" ../home/prog/plasma-tooltip-padding-libplasma.patch;
  crossPlasmaDesktop = crossPatched "plasma-desktop" ../home/prog/plasma-tooltip-padding-taskmanager.patch;
  # codex: after most llm-agents bumps its aarch64 build is uncached, and book
  # spends hours compiling the Rust workspace. Cross-compile it against
  # llm-agents' own nixpkgs (its cache's), linking that set's cached ARM
  # libraries so only codex itself is built.
  agents = inputs.llm-agents;
  agentsArm = import agents.inputs.nixpkgs { system = "aarch64-linux"; };
  agentsCross = import agents.inputs.nixpkgs {
    system = "x86_64-linux";
    crossSystem = "aarch64-linux";
  };
  # Both expressions assume a native build: their build-time helpers (the
  # cargo-skeleton script, zstd, the serialising rustc wrapper) must run on
  # top, so take those from buildPackages.
  hostSide = agentsCross.buildPackages;
  agentsScope = agentsCross.lib.makeScope agentsCross.newScope (self: {
    buildRustPackageCached = self.callPackage "${agents}/lib/build-rust-package-cached.nix" {
      inherit (hostSide) writers python3Packages zstd;
    };
  });
  crossCodex = agentsScope.callPackage "${agents}/packages/codex/package.nix" {
    doInstallCheck = false;
    inherit (hostSide) flock writeShellScript;
    inherit (agentsArm) aws-lc openssl rust-jemalloc-sys libgit2 oniguruma sqlite zlib zstd
      libcap ripgrep bubblewrap;
  };
  # saves: its Rust core and Qt front end, cross-built on top against book's
  # cached Qt (lib/saves.nix).
  armCross = native.pkgsCross.aarch64-multiplatform;
  crossSaves = { root, peer }: native.callPackage ./saves.nix {
    inherit root peer;
    src = inputs.saves;
    inherit (armCross) stdenv;
    inherit (armCross.buildPackages) cargo rustc;
    inherit (armCross.rustPlatform) cargoSetupHook;
    inherit (native.rustPlatform) importCargoLock;
    wrapQtAppsHook = crossQtWrap;
    hostQt = native.qt6.qtbase;
    rustTarget = armCross.stdenv.hostPlatform.rust.rustcTarget;
    inherit (arm) qt6 libglvnd vulkan-headers ffmpeg yt-dlp gallery-dl curl coreutils openssh;
  };
in {
  codex = crossCodex;
  saves = crossSaves;
  hyprvtb = crossPlugin; konsole = crossKonsole; oxygen = crossOxygen; headers = headersX86;
  libplasma = crossLibplasma; plasma-desktop = crossPlasmaDesktop;
}
