{ pkgs, lib, hostProfile, config, ... }:

# Put a bullet on this host's board when a named condition comes true, then
# shut up about it.
#
# This one exists for the weekly Claude-usage reset reminder. The reset time
# comes from `~/.claude.json`, and the behaviour lives in
# `board-reminder-files/board-reminder.py`.
#
# One board per host since 2026-07-30: each machine writes its own reminder,
# the live board check is the idempotence backstop, and `~/.claude.json` stays
# machine-local.
#
# Timer only: nothing emits a reset signal, so 15 minutes is the worst-case
# latency. The idle path is cheap, and once the reminder has fired it stays
# quiet.

# Use the board Python: the helper shells out to boardctl.py, which imports the
# board module set.
let reminderPython = hostProfile.boardPython pkgs;
in
{
  xdg.configFile."scripts/board-reminder.py" = {
    source = ./board-reminder-files/board-reminder.py;
    executable = true;
  };

  systemd.user.services.board-reminder = {
    Unit.Description = "Write a due reminder onto this host's board";
    Service = {
      Type = "oneshot";
      # Pinned PATH for the script and its helper; `%h` is not expanded in
      # Environment=.
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.coreutils ]}:${hostProfile.profilePathTail config.home.homeDirectory}"
      ];
      ExecStart = "${reminderPython} %h/.config/scripts/board-reminder.py";
      TimeoutStartSec = "2min";
    };
  };

  systemd.user.timers.board-reminder = {
    Unit.Description = "Check whether a board reminder has come due";
    Timer = {
      OnBootSec = "6min";
      # `OnStartupSec` is required too: the user manager starts at login, not at
      # boot, so `OnBootSec` alone can miss the window entirely.
      OnStartupSec = "6min";
      OnUnitActiveSec = "15min";
      # Catch resets that happened while the machine was off on the next boot.
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
