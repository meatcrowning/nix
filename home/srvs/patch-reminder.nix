{ pkgs, lib, host, config, ... }:

# The reminder shells out to boardctl.py, which imports the whole board module
# set (boardparse -> glyphs -> PySide6), so it must run under the board's python,
# NOT bare pkgs.python3. Same host split as home/prog/board.nix: nixpkgs
# python3+PySide6 on top, Fedora's system python3 (with python3-pyside6) on book.
let
  reminderPython =
    if host == "top"
    then "${pkgs.python3.withPackages (ps: [ ps.pyside6 ])}/bin/python3"
    else "/usr/bin/python3";
in

# Put a bullet on this host's board when ~/nix's package snapshot has gone stale,
# so the human upgrades on their own schedule. The whole rationale — why a
# reminder and NOT system.autoUpgrade (the pins; unsupervised nixpkgs rolls),
# how it recurs without a stamp file, and why it is host-neutral — lives in the
# script's docstring: read board-reminder-files/../patch-reminder-files/patch-reminder.py
# before changing anything here. Raised by the 2026-08-08 security audit.
#
# Sibling of board-reminder.nix and shaped identically (oneshot + timer, the
# same ambient-PATH problem, python3 running the script which shells out to
# boardctl.py with sys.executable). Deploys to top and book via home/; each
# writes only its own docs/board.<hostname>.md, and `update` is the correct
# upgrade alias on both, so nothing host-specific reaches the script.

{
  xdg.configFile."scripts/patch-reminder.py" = {
    source = ./patch-reminder-files/patch-reminder.py;
    executable = true;
  };

  systemd.user.services.patch-reminder = {
    Unit.Description = "Nudge the board when ~/nix's package snapshot is stale";
    Service = {
      Type = "oneshot";
      # As in board-reminder.nix: the ambient systemd-user PATH reaches none of
      # this, and both machines' profile layouts are named so it deploys to book
      # too. NOT %h in Environment — systemd expands specifiers in ExecStart only.
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.coreutils ]}:${config.home.homeDirectory}/.nix-profile/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/usr/bin:/bin"
      ];
      ExecStart = "${reminderPython} %h/.config/scripts/patch-reminder.py";
      TimeoutStartSec = "2min";
    };
  };

  systemd.user.timers.patch-reminder = {
    Unit.Description = "Check whether ~/nix's package snapshot has gone stale";
    Timer = {
      OnBootSec = "10min";
      OnStartupSec = "10min";
      OnUnitActiveSec = "1d";
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
