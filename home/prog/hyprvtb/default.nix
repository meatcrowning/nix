# Vertical titlebar window-decoration plugin ("hyprvtb"): compositor-drawn
# close/maximize buttons + rotated title on the right edge of every window,
# so titlebars are locked to windows frame-for-frame (unlike the old
# quickshell layer-shell titlebars, which could only chase window geometry
# over IPC). Built against the same hyprland package the system runs.
{
  lib,
  hyprland,
  hyprlandPlugins,
}:
hyprlandPlugins.mkHyprlandPlugin {
  pluginName = "hyprvtb";
  version = "0.1";
  src = ./.;

  inherit (hyprland) nativeBuildInputs;

  meta = {
    description = "Vertical per-window titlebars for Hyprland";
    license = lib.licenses.bsd3;
    platforms = lib.platforms.linux;
  };
}
