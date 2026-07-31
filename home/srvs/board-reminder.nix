{ pkgs, lib, host, config, ... }:

# Put a bullet on `docs/board.md` when a condition he named comes true, and
# then shut up about it.
#
# He asked for one on 2026-07-30: a reminder that fires AFTER his weekly Claude
# usage window resets, so the FOCUS-signal work (`docs/focus-signal.md`) gets
# picked up at that point rather than started against a 91%-spent week. The
# reset instant is not guessed — Claude Code caches it in `~/.claude.json`
# under `cachedUsageUtilization`, and the script reads it. All of the behaviour
# (where the timestamp comes from, the two ways a reset is observed, the
# fallback when it cannot be read, the host affinity and the disarm) is in
# board-reminder-files/board-reminder.py; read its docstring before changing
# anything here.
#
# BOTH MACHINES, ONE BULLET. `docs/` syncs both ways every five minutes, so a
# single bullet is already visible on both boards; two would be a duplicate,
# not coverage. `home/` is evaluated by BOTH hosts, so the unit exists on both
# and the duplicate is prevented in the script the way board-watch.nix prevents
# its own: `top` owns the write, book waits out a 24h grace and only writes if
# top never did, and either way the bullet's marker is looked for in the live
# board before writing. Nothing host-specific reaches this file — deliberately,
# since the affinity is data (a hostname) and not a build-time gate.
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

{
  xdg.configFile."scripts/board-reminder.py" = {
    source = ./board-reminder-files/board-reminder.py;
    executable = true;
  };

  systemd.user.services.board-reminder = {
    Unit.Description = "Write a due reminder onto ~/nix/docs/board.md";
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
      ExecStart = "${pkgs.python3}/bin/python3 %h/.config/scripts/board-reminder.py";
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
