{ pkgs, lib, ... }:

let
  oxygenVisualizer = pkgs.kdePackages.oxygen.overrideAttrs (old: {
    patches = (old.patches or []) ++ [
      ../../home/prog/oxygen-player-visualizer.patch
      ../../home/prog/oxygen-themed-vivaldi.patch
      ../../home/prog/oxygen-titlebar-seam.patch
    ];
  });
in {
  # KWin loads decorations from the system Qt plugin path, not an application's
  # wrapper.  A higher-priority copy keeps Oxygen selected while replacing only
  # the player-caption paint path.
  environment.systemPackages = [ (lib.hiPrio oxygenVisualizer) ];

  # KWin's Qt plugin path searches lam's home profile before the system
  # profile. Put the patched package at the same precedence: otherwise KWin
  # loads an ordinary Oxygen decoration pulled in by Qt application wrappers,
  # and Vivaldi's native bitmap bypasses the live tinted icon.
  home-manager.users.lam.home.packages = [ (lib.hiPrio oxygenVisualizer) ];
}
