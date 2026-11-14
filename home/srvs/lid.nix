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
# WHY IT IS NOT logind: the behaviour is a per-user, live setting, while
# HandleLidSwitch is system configuration fixed at rebuild. So instead a user
# service holds a `handle-lid-switch` BLOCK inhibitor for the
# whole login — logind then leaves the lid alone — and Hyprland's own switch
# binds (hyprland.lua, gated on host.laptop) call lid-close.sh, which does all
# four behaviours itself.
#
# The one consequence worth knowing: while this unit is running, logind ignores
# the lid, so lid close outside a Hyprland session (a TTY) does nothing. That is
# the same trade the logind drop-in would have made, minus the root. Stop the
# unit and logind's default suspend-on-close is back:
#   systemctl --user stop lid-inhibit.service

lib.mkIf (host == "air") {
  xdg.configFile."scripts/lid-close.sh" = {
    source = ./lid-files/lid-close.sh;
    executable = true;
  };

  systemd.user.services.lid-inhibit = {
    Unit.Description = "Hold logind's lid switch so hyprland can act on it (book)";
    Service = {
      # The system's systemd-inhibit, matching the running logind.
      ExecStart = ''/run/current-system/sw/bin/systemd-inhibit --what=handle-lid-switch --who=hyprland --why="lid close is a user setting (quickshell settings.json lidClose)" --mode=block ${pkgs.coreutils}/bin/sleep infinity'';
      Restart = "always";
      RestartSec = 5;
    };
    Install.WantedBy = [ "default.target" ];
  };
}
