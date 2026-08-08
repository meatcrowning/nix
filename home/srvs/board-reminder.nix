{ pkgs, lib, host, config, ... }:

# Put a bullet on this host's board (`docs/board.<hostname>.md`) when a
# condition he named comes true, and then shut up about it.
#
# He asked for one on 2026-07-30: a reminder that fires AFTER his weekly Claude
# usage window resets, so the FOCUS-signal work (`docs/focus-signal.md`) gets
# picked up at that point rather than started against a 91%-spent week. The
# reset instant is not guessed — Claude Code caches it in `~/.claude.json`
# under `cachedUsageUtilization`, and the script reads it. All of the behaviour
# (where the timestamp comes from, the two ways a reset is observed, the
# fallback when it cannot be read, and the disarm) is in
# board-reminder-files/board-reminder.py; read its docstring before changing
# anything here.
#
# BOTH MACHINES, ONE BULLET EACH. There is one board per host since 2026-07-30
# (`docs/board.top.md`, `docs/board.book.md` — the files sync, but only the
# machine a board is named for writes it), so each host simply writes its own
# bullet onto its own board. The host affinity and the 24h grace this used to
# carry are gone with the shared file that made them necessary; the marker check
# against the live board stays as the idempotence backstop. The condition is
# per-machine anyway — `~/.claude.json` does not sync. Nothing host-specific
# reaches this file, deliberately.
#
# NO PATH UNIT, unlike board-watch: nothing on this desktop writes a file when
# a usage window rolls over, so the timer is the only trigger there can be.
# Fifteen minutes is the worst-case latency between the reset and the bullet,
# which for a reminder that has already waited days is not worth tightening.
#
# It is CHEAP when there is nothing to do — a stamp file's existence, and then
# an exit — which is what makes a quarter-hourly timer reasonable. Once every
# reminder has fired the script does nothing at all for the rest of time; that
# is the intended resting state, not a leak.

# Must run under the board's python: it shells out to boardctl.py, which imports
# the whole board module set (boardparse -> glyphs -> PySide6). Bare pkgs.python3
# has no PySide6, so this failed at import on every tick. Same host split as
# home/prog/board.nix (nixpkgs python3+PySide6 on top, Fedora's on book).
let
  reminderPython =
    if host == "top"
    then "${pkgs.python3.withPackages (ps: [ ps.pyside6 ])}/bin/python3"
    else "/usr/bin/python3";
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
      # Same shape as board-watch.nix's, and for the same reason: the ambient
      # systemd-user PATH reaches none of this. `python3` runs the script,
      # which shells out to `boardctl.py` with the SAME interpreter (sys.executable)
      # so only the script's own tail matters here. The profile entries name
      # both machines' layouts because this deploys to book as well:
      #   ~/.nix-profile/bin              standalone home-manager (book)
      #   /etc/profiles/per-user/lam/bin  home-manager as a NixOS module (top)
      #   /run/current-system/sw/bin      NixOS system packages (top)
      #   /usr/bin:/bin                   Fedora (book)
      # NOT `%h`: systemd expands specifiers in ExecStart but not in
      # Environment=, so the home directory is interpolated here.
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.coreutils ]}:${config.home.homeDirectory}/.nix-profile/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/usr/bin:/bin"
      ];
      ExecStart = "${reminderPython} %h/.config/scripts/board-reminder.py";
      TimeoutStartSec = "2min";
    };
  };

  systemd.user.timers.board-reminder = {
    Unit.Description = "Check whether a board reminder has come due";
    Timer = {
      OnBootSec = "6min";
      # Required alongside OnBootSec: that one counts from SYSTEM boot, but the
      # user manager starts at login, so a login later than six minutes after
      # boot leaves the only elapse point in the past and the timer never fires
      # at all. See home/srvs/nix-docs.nix for the 14-hour outage that proved it.
      OnStartupSec = "6min";
      OnUnitActiveSec = "15min";
      # So a reset that happened while the machine was off is noticed at the
      # next boot instead of up to fifteen minutes into it.
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
