{ config, pkgs, lib, ... }:

{
  xdg.configFile."hypr/hypridle.conf".source = ./hypr-files/hypridle.conf;

  # hyprland.lua (active_border colour, via sed -i) and hyprpaper.conf (fully
  # rewritten) are both edited in place at runtime by
  # ~/.config/scripts/wal-set.sh — they need to be real, writable files, not
  # read-only Nix-store symlinks. Seed them once on first activation; leave
  # them alone afterwards so a rebuild doesn't reset the live palette/border
  # back to the template.
  home.activation.seedHyprMutableFiles = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    [ -e "$HOME/.config/hypr/hyprland.lua" ] || install -D -m644 ${./hypr-files/hyprland.lua} "$HOME/.config/hypr/hyprland.lua"
    [ -e "$HOME/.config/hypr/hyprpaper.conf" ] || install -D -m644 ${./hypr-files/hyprpaper.conf} "$HOME/.config/hypr/hyprpaper.conf"
  '';
}
