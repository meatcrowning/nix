{ host, pkgs, lib, ... }:

# `oxygenrc` is live input to both hosts' Plasma apps and their QML DeskStyle
# bridge. Values declared here are reset at each switch; undeclared values stay
# user-owned through oxygen-settings6 and fall back to Oxygen defaults. Keep
# animation durations and metrics undeclared so the apps follow the style.
{
  programs.plasma.configFile.oxygenrc = {
    # ---- the window drag ----------------------------------------------------
    # Oxygen's WindowManager drags the window from every unclaimed pixel
    # (`WD_FULL`, upstream's default) — including from inside a QQuickWidget,
    # which only ever sees a press nothing in the QML scene accepted. That is
    # the behaviour `apps/painter/qml/Root.qml` already defends against with a
    # full-window MouseArea at `z: -1000`, and that guard STAYS: it is
    # session-independent and it is the only thing protecting an app on a
    # machine where this file has not been applied.
    #
    # `WD_MINIMAL` is upstream's own supported narrowing — drag from the
    # titlebar, the menubar, the toolbar and empty dialog space, and nowhere
    # else — so every Oxygen window on the box behaves the way ours already had
    # to be made to. (`WindowDragWhiteList`/`BlackList` take window-class
    # patterns if a single app ever needs an exception.)
    Style.WindowDragEnabled = true;
    Style.WindowDragMode = "WD_MINIMAL";

    # ---- the two debug modes, named so they are known to exist --------------
    # WidgetExplorer prints the widget under the pointer with its full class
    # hierarchy; DrawWidgetRects outlines every primitive the style paints.
    # Both are Oxygen's own and both are the fastest way to see where a
    # QQuickWidget's boundary actually falls. Declared OFF rather than left
    # unset so a debugging session cannot leave one of them on for good.
    Style.WidgetExplorerEnabled = false;
    Style.DrawWidgetRects = false;

    # ---- his, captured ------------------------------------------------------
    # These four were already in the live file, set by hand or by the KCM
    # before this module existed. Declared so they survive a fresh machine and
    # so `book` gets the same window.
    Style.StackedWidgetTransitionsEnabled = true;
    ActiveShadow.Enabled = false;
    # Air alone uses normal titlebar controls.  Keeping this host-scoped makes
    # each profile durable across refreshes: top retains its small controls.
    Windeco.ButtonSize = if host == "air" then "ButtonNormal" else "ButtonSmall";

    # Titlebar geometry is shared across hosts. Leaving this mutable made
    # top's title text AlignLeft and book's AlignRight even though both selected
    # the same Oxygen decoration.
    Windeco.TitleAlignment = "AlignLeft";
  };

  # book's KWin and KDecoration are Fedora binaries. Build the patched Oxygen
  # decoration and widget style with Fedora's matching toolchain, never Nix's Qt/KF ABI:
  #   oxygen-vivaldi-build
  # Loading a replacement decoration into the running compositor remains the
  # user's visual step; the helper installs it for the next Plasma login.
  home.packages = lib.optionals (host == "air") [
    (pkgs.writeShellScriptBin "oxygen-vivaldi-build" ''
      set -euo pipefail
      SOURCE=${pkgs.kdePackages.oxygen.src}
      PATCH=${./oxygen-themed-vivaldi.patch}
      CONTENT_PATCH=${./oxygen-native-content.patch}
      DEST="$HOME/.local/lib64/qt6/plugins/org.kde.kdecoration3/org.kde.oxygen.so"
      FEDORA_VERSION=$(/usr/bin/rpm -q --qf '%{VERSION}' plasma-oxygen)
      SOURCE_VERSION=${pkgs.kdePackages.oxygen.version}

      [ "$FEDORA_VERSION" = "$SOURCE_VERSION" ] || {
        echo "oxygen-vivaldi-build: Fedora Oxygen $FEDORA_VERSION != source $SOURCE_VERSION" >&2
        exit 1
      }
      for tool in /usr/bin/cmake /usr/bin/gcc /usr/bin/g++ /usr/bin/git; do
        [ -x "$tool" ] || {
          echo "oxygen-vivaldi-build: $tool is missing" >&2
          exit 1
        }
      done

      WORK=$(/usr/bin/mktemp -d "$HOME/.cache/oxygen-vivaldi-build.XXXXXX")
      trap '/usr/bin/rm -rf -- "$WORK"' EXIT
      /usr/bin/tar -xf "$SOURCE" -C "$WORK"
      /usr/bin/mv "$WORK/oxygen-$SOURCE_VERSION" "$WORK/source"
      /usr/bin/chmod -R u+w "$WORK/source"
      /usr/bin/git apply --unsafe-paths --directory="$WORK/source" "$PATCH"
      /usr/bin/patch -d "$WORK/source" -p1 < "$CONTENT_PATCH"

      env -u CMAKE_PREFIX_PATH -u LIBRARY_PATH -u CPATH -u C_INCLUDE_PATH \
          -u CPLUS_INCLUDE_PATH -u PKG_CONFIG_PATH -u NIX_CFLAGS_COMPILE \
        /usr/bin/cmake -S "$WORK/source" -B "$WORK/build" -G Ninja \
          -DCMAKE_C_COMPILER=/usr/bin/gcc -DCMAKE_CXX_COMPILER=/usr/bin/g++ \
          -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
          -DBUILD_QT6=ON -DBUILD_QT5=OFF
      env -u CMAKE_PREFIX_PATH -u LIBRARY_PATH -u CPATH -u C_INCLUDE_PATH \
          -u CPLUS_INCLUDE_PATH -u PKG_CONFIG_PATH -u NIX_CFLAGS_COMPILE \
        /usr/bin/cmake --build "$WORK/build" --target oxygendecoration oxygen6 -j2
      /usr/bin/install -Dm755 "$WORK/build/bin/org.kde.oxygen.so" "$DEST"
      /usr/bin/install -Dm755 "$WORK/build/bin/oxygen6.so" \
        "$HOME/.local/lib64/qt6/plugins/styles/oxygen6.so"
      echo "oxygen-vivaldi-build: installed $DEST and native content style"
      echo "  takes effect at the next Plasma login"
    '')
  ];
}
