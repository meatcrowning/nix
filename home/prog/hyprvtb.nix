{ pkgs, ... }:

let
  # Compositor-side vertical titlebars — see ./hyprvtb/ for the C++ source
  # and why this exists (titlebars locked to windows, which no layer-shell
  # client can do). Built against the same nixpkgs hyprland the system runs;
  # the plugin refuses to load on a version hash mismatch, so after a
  # hyprland bump this rebuilds and keeps working automatically.
  hyprvtb = pkgs.callPackage ./hyprvtb { };
in
{
  # Stable path for hyprland.lua's hl.plugin.load() — the store path moves
  # on every rebuild, the symlink doesn't.
  xdg.configFile."hypr/plugins/libhyprvtb.so".source = "${hyprvtb}/lib/libhyprvtb.so";
}
