{ config, pkgs, lib, ... }:

{
  xdg.configFile."hypr/hypridle.conf".source = ./hypr-files/hypridle.conf;

  # hyprland.lua is edited in place at runtime — wal-set.sh seds the border and
  # seven plugin colours into it, cursor-recolor.sh the cursor theme name — so
  # it must be a real writable file, not a read-only Nix-store symlink.
  #
  # It used to be seeded ONCE and then left alone, which meant a rebuild never
  # updated it: `git pull && rebuild` silently applied nothing this file had
  # changed, and the live copy drifted behind source indefinitely. It is now
  # RECONCILED on every switch instead — the nix source wins on structure, the
  # live file's runtime-owned values are carried across. tools/seed-drift.sh
  # stays as the tripwire for the reconciler missing a value.
  #
  # hyprpaper.conf used to be seeded here for the same reason (wal-set.sh
  # rewrote it wholesale). The wallpaper is drawn by the Quickshell panel now,
  # so there is no hyprpaper and no config file to seed.
  home.activation.seedHyprMutableFiles = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    run bash ${../../tools/seed-reconcile.sh} hyprland-lua \
      ${./hypr-files/hyprland.lua} "$HOME/.config/hypr/hyprland.lua" || true
  '';
}
