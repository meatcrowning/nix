{ pkgs, lib, host, ... }:

# kwin-momentum — packaging + session wiring for the KWin touchpad-momentum
# plugin whose source lives at home/prog/kwin-momentum/src/. See the runbook
# docs/agents/kwin-momentum-plugin-runbook.md.
#
# book ONLY (host == "air"). The plugin is a KWin BINARY extension that must
# link Fedora's exact libkwin.so.6 / Qt6 ABI, so:
#   * it cannot be a nix derivation — a nix-built .so links nix's Qt6/glibc and
#     Fedora's kwin_wayland refuses to load it (runbook §0). The build runs on
#     book with Fedora's /usr/bin toolchain; the .so is Fedora system state,
#     not a nix output.
#   * top runs nix's OWN KWin (different ABI) and has no touchpad, so the plugin
#     is meaningless there — nothing here deploys on top.
#
# This module therefore does only the two things nix legitimately CAN do:
#   1. put the user plugin dir on QT_PLUGIN_PATH so KWin discovers the .so, and
#   2. ship `kwin-momentum-build`, the Fedora-toolchain build+install helper.
# The .so is never a nix output, and loading it into a live KWin stays the
# user's step (runbook §5).
lib.mkIf (host == "air") {
  # 1. Session env. Plasma sources every executable *.sh in
  #    ~/.config/plasma-workspace/env/ before kwin_wayland starts, so this is
  #    the reliable way to reach the GUI session's env on a Fedora Plasma login
  #    (home.sessionVariables only reaches shells). ~/.local/lib64/qt6/plugins
  #    is not a default Qt plugin path, so without this KWin never scans it.
  xdg.configFile."plasma-workspace/env/kwin-momentum-plugin-path.sh" = {
    executable = true;
    text = ''
      # Managed by home/prog/kwin-momentum.nix — do not hand-edit.
      # Let KWin discover the user-built momentum plugin. Discovery only; the
      # plugin still stays disabled until kwinrc enables it (runbook §5), so this
      # cannot auto-activate momentum on login.
      case ":''${QT_PLUGIN_PATH:-}:" in
        *":$HOME/.local/lib64/qt6/plugins:"*) ;;
        *) export QT_PLUGIN_PATH="$HOME/.local/lib64/qt6/plugins''${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}" ;;
      esac
    '';
  };

  # 2. The build helper. Compiles with Fedora's toolchain (never nix's — bare
  #    cmake/gcc on a login shell are nix's and can't see /usr/lib64, so the nix
  #    build env is stripped and the Fedora compilers forced) and installs into
  #    the user plugin dir. Idempotent; run it after editing src/. It does NOT
  #    load or restart KWin — that is the user's call.
  home.packages = [
    (pkgs.writeShellScriptBin "kwin-momentum-build" ''
      set -euo pipefail
      SRC=/home/lam/nix/home/prog/kwin-momentum/src
      BUILD="''${XDG_CACHE_HOME:-$HOME/.cache}/kwin-momentum-build"
      DEST="$HOME/.local/lib64/qt6/plugins/kwin/plugins"

      for p in /usr/bin/cmake /usr/bin/gcc /usr/bin/g++; do
        [ -x "$p" ] || {
          echo "kwin-momentum-build: $p is missing." >&2
          echo "  Need Fedora's toolchain + devel headers:" >&2
          echo "  sudo dnf install kwin-devel qt6-qtbase-devel extra-cmake-modules libepoxy-devel gcc-c++" >&2
          exit 1
        }
      done

      echo "kwin-momentum-build: configuring ($SRC -> $BUILD)"
      env -u CMAKE_PREFIX_PATH -u LIBRARY_PATH -u CPATH -u C_INCLUDE_PATH \
          -u CPLUS_INCLUDE_PATH -u PKG_CONFIG_PATH -u NIX_CFLAGS_COMPILE \
        /usr/bin/cmake -B "$BUILD" -S "$SRC" \
          -DCMAKE_C_COMPILER=/usr/bin/gcc -DCMAKE_CXX_COMPILER=/usr/bin/g++ \
          -DCMAKE_BUILD_TYPE=Release
      env -u CMAKE_PREFIX_PATH -u LIBRARY_PATH -u CPATH -u C_INCLUDE_PATH \
          -u CPLUS_INCLUDE_PATH -u PKG_CONFIG_PATH -u NIX_CFLAGS_COMPILE \
        /usr/bin/cmake --build "$BUILD"

      # KDECMakeSettings drops the artifact in build/bin/, not build/.
      install -Dm755 "$BUILD/bin/kwin_momentum.so" "$DEST/kwin_momentum.so"
      echo "kwin-momentum-build: installed $DEST/kwin_momentum.so"
      echo -n "  ABI: "; readelf -d "$DEST/kwin_momentum.so" | grep -o 'libkwin.so.6' | head -1 || echo '??'

      echo
      echo "NOT loaded. To try it in YOUR live Plasma session (runbook §5 — your"
      echo "call, never an agent's; it replaces the running compositor):"
      echo "  kwriteconfig6 --file kwinrc --group Plugins --key kwin_momentumEnabled true"
      echo "  kwin_wayland --replace &"
    '')
  ];
}
