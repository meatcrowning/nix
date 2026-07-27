{ config, pkgs, lib, ... }:

{
  xdg.configFile."hypr/hypridle.conf".source = ./hypr-files/hypridle.conf;

  # hyprland.lua (active_border colour, via sed -i) is edited in place at runtime
  # by ~/.config/scripts/wal-set.sh — it needs to be a real, writable file, not a
  # read-only Nix-store symlink. Seed it once on first activation; leave it alone
  # afterwards so a rebuild doesn't reset the live palette/border back to the
  # template.
  #
  # hyprpaper.conf used to be seeded here for the same reason (wal-set.sh
  # rewrote it wholesale). The wallpaper is drawn by the Quickshell panel now,
  # so there is no hyprpaper and no config file to seed.
  home.activation.seedHyprMutableFiles = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    [ -e "$HOME/.config/hypr/hyprland.lua" ] || install -D -m644 ${./hypr-files/hyprland.lua} "$HOME/.config/hypr/hyprland.lua"
  '';
}
