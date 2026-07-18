{ config, pkgs, ... }:

{
  programs.hyprland.enable = true;
  programs.labwc.enable = true;

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
