{ host, pkgs, lib, ... }:

# Lid-close behaviour on `book` (the MacBook Air) — user-settable.
#
# `top` is a desktop with no lid at all, so this whole module is gated on
# host == "air" and nothing here is evaluated there.
#
# WHERE THE SETTING LIVES: `lidClose` in ~/.config/quickshell/settings.json
# ("suspend" | "lock" | "blank" | "nothing", default "suspend"), drawn by the
# Settings window's Lock & Power page. lid-close.sh reads it on every lid event,
# so a change applies immediately — nothing to restart.
#
# WHY IT IS NOT logind: HandleLidSwitch lives in /etc/systemd/logind.conf, which
# on book is Fedora system state this repo (home-manager only) cannot write, and
# a hand-edit there would have to be redone by hand after a reinstall. So
# instead a user service holds a `handle-lid-switch` BLOCK inhibitor for the
# whole login — logind then leaves the lid alone — and Hyprland's own switch
# binds (hyprland.lua, gated on host.laptop) call lid-close.sh, which does all
# four behaviours itself. No root, nothing outside this repo to redo.
#
# The one consequence worth knowing: while this unit is running, logind ignores
# the lid, so lid close outside a Hyprland session (a TTY) does nothing. That is
# the same trade the logind drop-in would have made, minus the root. Stop the
# unit and Fedora's default suspend-on-close is back:
#   systemctl --user stop lid-inhibit.service

lib.mkIf (host == "air") {
  xdg.configFile."scripts/lid-close.sh" = {
    source = ./lid-files/lid-close.sh;
    executable = true;
  };

  systemd.user.services.lid-inhibit = {
    Unit.Description = "Hold logind's lid switch so hyprland can act on it (book)";
    Service = {
      # /usr/bin — book is Fedora, and systemd is the OS's, not nixpkgs'; the
      # inhibitor has to be taken against the running system logind.
      ExecStart = ''/usr/bin/systemd-inhibit --what=handle-lid-switch --who=hyprland --why="lid close is a user setting (quickshell settings.json lidClose)" --mode=block ${pkgs.coreutils}/bin/sleep infinity'';
      Restart = "always";
      RestartSec = 5;
    };
    Install.WantedBy = [ "default.target" ];
  };
}
