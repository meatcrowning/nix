# Vertical titlebar window-decoration plugin ("hyprvtb"): compositor-drawn
# close/maximize buttons + rotated title on the right edge of every window,
# so titlebars are locked to windows frame-for-frame (unlike the old
# quickshell layer-shell titlebars, which could only chase window geometry
# over IPC). Built against the pinned hyprland flake input (see flake.nix and
# ./PORTING.md), never nixpkgs' — the plugin compiles against Hyprland's
# internal headers, so the two must move together and only on purpose.
{
  lib,
  hyprland,
  hyprlandPlugins,
  librsvg,
}:
hyprlandPlugins.mkHyprlandPlugin {
  pluginName = "hyprvtb";
  version = "0.1.1";
  src = ./.;

  inherit (hyprland) nativeBuildInputs;

  # librsvg: renders each window's program icon (the breeze theme is all-SVG,
  # and our own app icons are SVG too) into the new titlebar icon slot. pango/
  # cairo/fontconfig already come in via hyprland.buildInputs; librsvg does not.
  buildInputs = [ librsvg ];

  # Seam enforcement — the containment strategy in PORTING.md only works if it
  # can't quietly erode, so both halves are checked at build time.
  #
  # 1. Volatile Hyprland internals may be named ONLY in vtbCompat.hpp. That is
  #    what turns the next compositor bump from a ~180-site sprawl into a
  #    one-file diff.
  # 2. No raw WP<CVtbDeco> anywhere: decorations are unique-owned, so a weak
  #    ref to one must be a CDecoRef (globals.hpp), which has no lock() to
  #    abort the compositor with under hyprutils >= 0.14.0.
  doCheck = true;
  checkPhase = ''
    runHook preCheck

    # cmake configures/builds in a `build` subdir, so checkPhase starts there —
    # the sources being checked are one level up. installPhase runs from the
    # build dir, so come back before returning (or it silently installs
    # nothing).
    buildDir=$PWD
    cd "$NIX_BUILD_TOP/$sourceRoot"
    fail=0

    if grep -rn --include=\*.cpp --include=\*.hpp \
        -e 'g_pCompositor' -e 'g_pHyprRenderer' -e 'g_pHyprOpenGL' \
        -e 'g_pInputManager' -e 'g_pSeatManager' -e 'g_pKeybindManager' \
        -e 'g_pEventLoopManager' \
        -e 'Desktop::viewState' -e 'Desktop::windowState' -e 'Desktop::focusState' \
        -e 'State::monitorState' -e 'Fullscreen::controller' -e 'Pointer::Cursor' \
        -e 'positionAnimation' -e 'sizeAnimation' -e 'm_layerSurfaceLayers' \
        -e 'm_renderPass' -e 'm_renderData' -e 'Config::mgr' -e 'g_pKeybindManager' \
        -e 'm_realPosition' -e 'm_realSize' -e 'm_snapshotFB' -e 'makeSnapshot' \
        -e 'changeWindowZOrder' -e 'vectorToWindow' -e 'vectorToLayerSurface' \
        -e 'getMonitorFromVector' -e 'Cursor::overrideController' \
        . | grep -v '^\./vtbCompat\.hpp:'; then
      echo "SEAM VIOLATION: volatile Hyprland internals belong in vtbCompat.hpp only (see PORTING.md)."
      fail=1
    fi

    if grep -rn --include=\*.cpp --include=\*.hpp -E '^[[:space:]]*#define[[:space:]]+private' .; then
      echo "SEAM VIOLATION: no reaching into Hyprland classes through the preprocessor — find the public accessor (see PORTING.md)."
      fail=1
    fi

    if grep -rn --include=\*.cpp --include=\*.hpp 'config\.[a-zA-Z]*->value()' . | grep -v '^\./globals\.hpp:'; then
      echo "SEAM VIOLATION: read config through the Cfg:: accessors in globals.hpp (see PORTING.md)."
      fail=1
    fi

    if grep -rn --include=\*.cpp --include=\*.hpp 'WP<CVtbDeco>' . | grep -v '^\./globals\.hpp:'; then
      echo "SEAM VIOLATION: use CDecoRef, not a raw WP<CVtbDeco> — lock() over a unique-owned deco aborts the compositor (see PORTING.md)."
      fail=1
    fi

    [ "$fail" = 0 ] || exit 1
    cd "$buildDir"

    runHook postCheck
  '';

  meta = {
    description = "Vertical per-window titlebars for Hyprland";
    license = lib.licenses.bsd3;
    platforms = lib.platforms.linux;
  };
}
