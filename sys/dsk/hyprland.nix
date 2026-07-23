{ config, pkgs, ... }:

{
  programs.hyprland.enable = true;

  # xdg-desktop-portal routing for the Hyprland session. programs.hyprland
  # already enables xdg.portal + the hyprland backend; without an explicit
  # config, routing falls back to the hyprland-portals.conf shipped inside
  # xdph. Make it explicit: screencast/screenshot go to the hyprland backend,
  # file dialogs + the dark-mode Settings signal go to KDE (so they match the
  # kdeglobals/wal theming), and gtk is the general fallback for everything
  # else. All these backends are already present on the system (Plasma pulls
  # in -kde/-gtk); this only picks who answers which interface.
  # Written to /etc/xdg-desktop-portal/hyprland-portals.conf (used when
  # $XDG_CURRENT_DESKTOP contains "hyprland", which the session sets).
  xdg.portal.config.hyprland = {
    default = [ "hyprland" "gtk" ];
    "org.freedesktop.impl.portal.FileChooser" = [ "kde" ];
    "org.freedesktop.impl.portal.Settings" = [ "kde" ];
  };

  # Lock.qml (quickshell/Lock.qml) authenticates through this PAM service by
  # name (PamContext { config: "quickshell-lock" }) — without it declared,
  # PAM has nothing to open for that service name and Lock.qml reports "auth
  # unavailable". Empty options give the same baseline pam_unix stack NixOS
  # already generates for swaylock/vlock (see /etc/pam.d/swaylock) — plain
  # password auth, no desktop-environment dependency, matching what the
  # migration source's quickshell-lock.pam (written for Fedora's system-auth
  # include, which doesn't exist on NixOS) was actually going for.
  security.pam.services.quickshell-lock = {};
}
