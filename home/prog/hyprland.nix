{ config, pkgs, lib, ... }:

{
  xdg.configFile."hypr/hypridle.conf".source = ./hypr-files/hypridle.conf;

  # Keep a writable copy for runtime palette/cursor changes. Reconcile source
  # structure on activation while carrying those runtime-owned values.
  home.activation.seedHyprMutableFiles = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    run bash ${../../tools/seed-reconcile.sh} hyprland-lua \
      ${./hypr-files/hyprland.lua} "$HOME/.config/hypr/hyprland.lua" || true
  '';
}
