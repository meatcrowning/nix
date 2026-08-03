{ ... }:

# Give the Hyprland session a systemd target, so `graphical-session.target`
# actually becomes active.
#
# Nothing in a bare Hyprland session activates `graphical-session.target` —
# that is why the units in this repo (quickshell-panel, wal-*, easyeffects,
# udiskie) are ordered `After=` it but started EXPLICITLY from hyprland.lua
# rather than `WantedBy=` it. That pattern works for units we own.
#
# It cannot work for units we do not. Measured on book 2026-08-02:
#
#     xdg-desktop-portal.service:  Requisite=graphical-session.target
#
# `Requisite=` means the target must ALREADY be active and will never be pulled
# in, so an explicit `systemctl --user start xdg-desktop-portal.service` fails
# with "Dependency failed" exactly like the login-time attempt does — and
# `graphical-session.target` itself sets RefuseManualStart, so it cannot be
# started by hand either. The portal was therefore dead for the whole session:
# every file picker, screen-share and `org.freedesktop.portal.Desktop`
# activation returned NameHasNoOwner.
#
# The way out is the one every other Wayland compositor ships (sway-session.
# target, and Hyprland's own upstream unit): a session target that BindsTo the
# generic one. BindsTo pulls it in on start, and drops it again when this one
# stops, so the lifecycle still matches the compositor's. hyprland.lua starts
# this first thing in `hyprland.start`.
#
# Host-neutral on purpose: this is a property of running Hyprland without a
# session manager, not of either machine, and both `top` and `book` run it that
# way. The explicit starts in hyprland.lua stay as they are — they are what
# makes the ordering deterministic, and starting an already-running unit is a
# no-op.
{
  systemd.user.targets.hyprland-session = {
    Unit = {
      Description = "Hyprland compositor session";
      Documentation = [ "man:systemd.special(7)" ];
      BindsTo = [ "graphical-session.target" ];
      Wants = [ "graphical-session-pre.target" ];
      After = [ "graphical-session-pre.target" ];
    };
  };
}
