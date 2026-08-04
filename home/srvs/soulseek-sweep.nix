{ pkgs, lib, host, config, ... }:

# Periodically drain the Soulseek missing-track backlog so the download queue
# doesn't idle. apps/player/tools/soulseek-missing.py submits a batch of
# searches to the local slskd daemon (home/prog/slskd.nix) and queues matches
# for its 50-slot downloader; nothing ran it on a schedule, so the queue
# drained to a handful and stopped until kicked by hand. This is the scheduled
# kick. All the "is slskd even up" / kill-switch / non-overlap logic is in the
# wrapper — read soulseek-sweep-files/soulseek-sweep.sh before changing this.
#
# TOP-ONLY, and it is not a preference. The music library physically lives on
# `top`'s SSD (/run/media/lam/SSD/aud); `book` sees it only as an SMB mount back
# to `top` (slskd.nix says as much, and shares nothing there for that reason),
# and the whole missing-track pipeline — the spotify-dump work list, the player
# library.db it diffs against, the slskd share — is `top`'s. Running the sweep
# on `book` would download into book and import the files back over the network
# to `top`'s SSD, double-handling identical content. So it is gated on the host
# module arg rather than left to silently no-op on book: on `book` the unit is
# simply not present. If book ever grows its own local library, revisit.
#
# No path unit (unlike sort-downloads / board-watch): nothing local changes
# when a track becomes wanted, so there is nothing to watch — the timer is the
# only trigger.

lib.mkIf (host == "top") {
  xdg.configFile."scripts/soulseek-sweep.sh" = {
    source = ./soulseek-sweep-files/soulseek-sweep.sh;
    executable = true;
  };

  systemd.user.services.soulseek-sweep = {
    Unit = {
      Description = "Keep the Soulseek download pool fed via slskd";
      # A crash must not permanently give up (the pool would sit idle until the
      # next reboot or hand-start): disable the start-rate limit so Restart
      # below can retry indefinitely. The timer re-checks anyway.
      StartLimitIntervalSec = 0;
    };
    Service = {
      # Long-running feeder (soulseek-missing.py --watch), not a one-shot batch:
      # a periodic one-shot could not hold the pool at a low-water mark. The
      # wrapper `exec`s the python, so systemd tracks it directly.
      Type = "simple";
      # Pinned so the unit doesn't lean on the ambient systemd-user PATH.
      # curl = the slskd reachability pre-check; python3 runs the feeder;
      # coreutils/util-linux supply date and flock. The profile dirs are
      # appended (board-notify.nix / board-reminder.nix do the same) so
      # `shutil.which("player")` in soulseek-missing.py's player_python()
      # can actually find the `player` wrapper: without them it silently
      # fell back to this bare python3, which has no mutagen, so every
      # completed download's import-into-library step
      # (player-add.py) failed with ModuleNotFoundError and downloads piled
      # up in ~/.local/share/slskd/downloads/ instead of reaching aud/.
      # PYTHONUNBUFFERED so the days-long run's per-poll output reaches journald
      # promptly (stdout to a pipe is block-buffered otherwise).
      Environment = [
        "PATH=${lib.makeBinPath [
          pkgs.coreutils
          pkgs.util-linux
          pkgs.curl
          pkgs.python3
        ]}:${config.home.homeDirectory}/.nix-profile/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/usr/bin:/bin"
        "PYTHONUNBUFFERED=1"
      ];
      ExecStart = "${pkgs.bash}/bin/bash %h/.config/scripts/soulseek-sweep.sh";
      # Self-heal: a crash (unhandled exception, slskd dropping mid-run past the
      # loop's own retry) restarts after 30s. A clean drain (exit 0 — nothing
      # left to search and nothing in flight) or a slskd-down pre-check skip
      # (also exit 0) stays stopped; the timer re-checks. The loop itself
      # already catches per-poll blips (see watch_loop), so on-failure only
      # fires on a genuine crash, not on a transient slskd hiccup.
      Restart = "on-failure";
      RestartSec = 30;
      # SIGTERM sets STOP; the loop finishes the current search (up to the
      # search timeout, ~90s) and exits. Give it room before SIGKILL.
      TimeoutStopSec = "120s";
    };
  };

  systemd.user.timers.soulseek-sweep = {
    Unit.Description = "(Re)start the Soulseek pool feeder if it isn't running";
    Timer = {
      # The feeder normally runs continuously; `systemctl start` on an already-
      # active simple service is a no-op, so this timer only matters after a
      # clean drain (it re-checks for newly-missing tracks) or a reboot. (It is
      # not enabled while the download pipeline is stopped — see the Install
      # block below.)
      OnBootSec = "5min";
      # Required alongside OnBootSec: it counts from system boot, but the user
      # manager starts at login; a login later than the offset would otherwise
      # leave the only elapse point in the past and never fire (see nix-docs.nix).
      OnStartupSec = "5min";
      # 30 min after the service goes INACTIVE (a clean drain), re-check for
      # newly-missing tracks. Deliberately OnUnitInactiveSec, not …ActiveSec:
      # the service runs continuously, so an …ActiveSec timer would keep firing
      # against an already-active unit (a no-op, but log spam); …InactiveSec
      # fires only while it is stopped, which is the only time a re-check helps.
      OnUnitInactiveSec = "30min";
      Persistent = true;
    };
    # Deliberately no Install.WantedBy since 2026-08-03 (pipeline stopped at
    # his request): a home-manager switch must not re-enable this timer. The
    # unit file stays, so the pool feeder can be re-armed by hand later —
    # `systemctl --user enable --now soulseek-sweep.timer` (or re-add this
    # block) when the download pipeline is allowed to run automatically again.
  };
}
