{ pkgs, lib, ... }:

let
  oxygenVisualizer = pkgs.kdePackages.oxygen.overrideAttrs (old: {
    patches = (old.patches or []) ++ [ ../../home/prog/oxygen-player-visualizer.patch ];
  });
in {
  # KWin loads decorations from the system Qt plugin path, not an application's
  # wrapper.  A higher-priority copy keeps Oxygen selected while replacing only
  # the player-caption paint path.
  environment.systemPackages = [ (lib.hiPrio oxygenVisualizer) ];
}
