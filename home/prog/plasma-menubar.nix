{ pkgs, lib, config, host, ... }:

# The stock appmenu imports native DBus menus. This adjacent applet supplies
# desktop menus, a Window fallback, and Vivaldi's own menus over a loopback
# WebSocket restricted to the packaged browser UI origin. Vivaldi's resource
# injection lives in home/pkgs/desktop/net.nix (top only; book uses Flatpak).
#
# NOTE the whole package directory is deployed as ONE symlink to a store path.
# Per-file symlinks do not work: KPackage canonicalises every file it opens and
# rejects anything resolving outside the package root — the same trap
# home/prog/plasma-notif-gap.nix documents.

let
  pkgId = "org.kde.lam.menubar";

  metadata = builtins.toJSON {
    KPackageStructure = "Plasma/Applet";
    KPlugin = {
      Id = pkgId;
      Name = "Menu Bar";
      Description = "Always-visible app and desktop menus, macOS style";
      Category = "Windows and Tasks";
      Icon = "application-menu";
      EnabledByDefault = true;
      Version = "1.0";
    };
    "X-Plasma-API-Minimum-Version" = "6.0";
  };

  package = pkgs.runCommand pkgId { } ''
    mkdir -p $out/contents/ui
    cp ${pkgs.writeText "metadata.json" metadata} $out/metadata.json
    cp ${./plasma-menubar-files/main.qml} $out/contents/ui/main.qml
  '';

  # QML cannot create a native menu window. This tiny Applet interface does:
  # it owns the QMenu, makes it transient to the panel, and maps it immediately
  # below the selected category. Keeping the menu data/actions in QML leaves
  # the desktop's actual behavior in the readable fallback source.
  nativeInterface = pkgs.stdenv.mkDerivation {
    pname = "plasma-menubar-native-interface";
    version = "1";
    src = ./plasma-menubar-files/native;
    dontWrapQtApps = true;
    doCheck = true;
    checkPhase = ''
      runHook preCheck
      unset DISPLAY WAYLAND_DISPLAY
      export QT_QPA_PLATFORM=offscreen
      source ${../../tools/lib/session-guard.sh}
      sg_require_offscreen
      ctest --output-on-failure
      runHook postCheck
    '';
    nativeBuildInputs = [
      pkgs.cmake
      pkgs.ninja
      pkgs.kdePackages.extra-cmake-modules
      pkgs.pkg-config
    ];
    buildInputs = [
      pkgs.qt6.qtbase
      pkgs.qt6.qtdeclarative
      pkgs.qt6.qtwebsockets
      pkgs.kdePackages.libplasma
      pkgs.kdePackages.kcoreaddons
      pkgs.kdePackages.kconfig
    ];
  };
in
{
  # Fedora Plasma cannot load Nix's Qt plugins. Like Oxygen on book, build
  # this interface against Fedora's libraries and install in its user path.
  # Prerequisites: libplasma-devel, qt6-qtwebsockets-devel, KF6 development
  # packages and the native CMake/GCC toolchain. Run after source updates.
  home.packages = [ nativeInterface ] ++ lib.optionals (host == "air") [
    (pkgs.writeShellScriptBin "plasma-menubar-build" ''
      set -euo pipefail
      WORK=$(/usr/bin/mktemp -d "$HOME/.cache/plasma-menubar-build.XXXXXX")
      trap '/usr/bin/rm -rf -- "$WORK"' EXIT
      env -u CMAKE_PREFIX_PATH -u LIBRARY_PATH -u CPATH -u C_INCLUDE_PATH \
          -u CPLUS_INCLUDE_PATH -u PKG_CONFIG_PATH -u NIX_CFLAGS_COMPILE \
        /usr/bin/cmake -S ${./plasma-menubar-files/native} -B "$WORK" -G Ninja \
          -DCMAKE_C_COMPILER=/usr/bin/gcc -DCMAKE_CXX_COMPILER=/usr/bin/g++ \
          -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
      /usr/bin/cmake --build "$WORK" -j2
      (
        unset DISPLAY WAYLAND_DISPLAY
        export QT_QPA_PLATFORM=offscreen
        source ${../../tools/lib/session-guard.sh}
        sg_require_offscreen
        /usr/bin/ctest --test-dir "$WORK" --output-on-failure
      )
      /usr/bin/install -Dm755 "$WORK/org.kde.lam.menubar.so" \
        "$HOME/.local/lib64/qt6/plugins/plasma/applets/org.kde.lam.menubar.so"
      echo "Menu interface installed; reload Plasma to use it."
    '')
  ];
  xdg.dataFile."plasma/plasmoids/${pkgId}".source = package;

  # Installing a plasmoid package never instantiates it, and Plasma has no
  # declarative panel layout. Add exactly one, to whichever panel already holds
  # the stock appmenu applet (that is the bar this belongs beside), falling back
  # to the top panel. The scan makes logins and rebuilds idempotent.
  #
  # The scripting API can only APPEND — there is no reorder in
  # `shell/scripting/containment.h` — so a first-ever install lands it at the
# end of the panel and its place after the appmenu is set once, by hand, in
  # AppletOrder. The one obsolete fixed spacer directly before this applet is
  # removed: it is a blank gutter between Kickoff and the first menu label.
  systemd.user.services.plasma-menubar = {
    Unit = {
      Description = "Add the always-visible menu bar to the Plasma panel";
      After = [ "graphical-session.target" ];
      ConditionEnvironment = "KDE_FULL_SESSION=true";
    };
    Service = {
      Type = "oneshot";
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.coreutils ]}:${config.home.homeDirectory}/.nix-profile/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/usr/bin:/bin"
      ];
      ExecStart = pkgs.writeShellScript "plasma-menubar-install" ''
        for attempt in $(seq 1 60); do
          if qdbus org.kde.plasmashell /PlasmaShell \
              org.kde.PlasmaShell.evaluateScript ${lib.escapeShellArg ''
                var present = false;
                var menuPanel = null;
                var menuIndex = -1;
                var beside = -1;
                var top = -1;
                for (var i = 0; i < panelIds.length; ++i) {
                    var panel = panelById(panelIds[i]);
                    if (panel.location === "top" && top < 0) top = panelIds[i];
                    var widgets = panel.widgets();
                    for (var j = 0; j < widgets.length; ++j) {
                        if (widgets[j].type === "${pkgId}") {
                            present = true;
                            menuPanel = panel;
                            menuIndex = j;
                        }
                        if (widgets[j].type === "org.kde.plasma.appmenu") beside = panelIds[i];
                    }
                }
                var target = beside >= 0 ? beside : top;
                if (!present && target >= 0) panelById(target).addWidget("${pkgId}");
                if (present && menuIndex > 0) {
                    var before = menuPanel.widgets()[menuIndex - 1];
                    if (before.type === "org.kde.plasma.panelspacer") before.remove();
                }
              ''} >/dev/null 2>&1; then
            exit 0
          fi
          sleep 1
        done
        exit 1
      '';
    };
    Install.WantedBy = [ "graphical-session.target" ];
  };
}
