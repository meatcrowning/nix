{ config, pkgs, lib, ... }:

# labwc as a third selectable session at the greeter, next to Hyprland and
# Plasma. `defaultSession` stays "hyprland" — this only adds an entry to the
# list ly reads from `services.displayManager.sessionData`.
#
# The package carries `passthru.providedSessions = [ "labwc" ]` and ships
# share/wayland-sessions/labwc.desktop, which is exactly what sessionPackages
# demands; the module lndirs that entry into the greeter's session directory.
# Its Exec line is a bare `labwc`, so the binary has to be resolvable from the
# session's PATH — hence systemPackages as well, not sessionPackages alone.
#
# The user-facing half (labwc-tweaks, labwc-menu-generator, the seeded
# ~/.config/labwc) is home/prog/labwc.nix.
{
  services.displayManager.sessionPackages = [ pkgs.labwc ];
  environment.systemPackages = [ pkgs.labwc ];

  # xdg-desktop-portal routing for a labwc session, made explicit for the same
  # reason the Hyprland one is (sys/dsk/hyprland.nix): labwc ships its own
  # labwc-portals.conf naming wlr + gtk, and leaving routing to it would send
  # file dialogs to gtk, where they miss the kdeglobals/wal theming every other
  # session's dialogs get. Written to /etc/xdg-desktop-portal/labwc-portals.conf
  # and used when $XDG_CURRENT_DESKTOP contains "labwc", which the session sets.
  #
  # wlr is the only backend here not already on the system: screencast and
  # screenshot under a plain wlroots compositor have no other answer (the
  # hyprland backend refuses a non-Hyprland compositor).
  xdg.portal.extraPortals = [ pkgs.xdg-desktop-portal-wlr ];
  xdg.portal.config.labwc = {
    default = [ "gtk" ];
    "org.freedesktop.impl.portal.ScreenCast" = [ "wlr" ];
    "org.freedesktop.impl.portal.Screenshot" = [ "wlr" ];
    "org.freedesktop.impl.portal.FileChooser" = [ "kde" ];
    "org.freedesktop.impl.portal.Settings" = [ "kde" ];
  };
}
