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
      Description = "Drain the Soulseek missing-track backlog via slskd";
      # The timer fires every 30 min; a slow sweep can outlive that, but the
      # wrapper takes a non-blocking flock so an overrun tick is a clean no-op.
      # Keep the default start limit — this is a low-frequency timer.
    };
    Service = {
      Type = "oneshot";
      # Pinned so the unit doesn't lean on the ambient systemd-user PATH.
      # curl = the slskd reachability pre-check; python3 runs the sweep;
      # coreutils/util-linux supply date and flock. python3 also needs the
      # per-user profile for nothing here (stdlib only), but pin it anyway.
      Environment = [
        "PATH=${lib.makeBinPath [
          pkgs.coreutils
          pkgs.util-linux
          pkgs.curl
          pkgs.python3
        ]}"
      ];
      ExecStart = "${pkgs.bash}/bin/bash %h/.config/scripts/soulseek-sweep.sh";
      # A batch searches up to 40 tracks one at a time (each 18-90s), so a run
      # can take ~20-30 min. This is the outer guard on a wedged run; the flock
      # keeps the next tick from piling on while it is still going.
      TimeoutStartSec = "45min";
    };
  };

  systemd.user.timers.soulseek-sweep = {
    Unit.Description = "Periodically drain the Soulseek missing-track backlog";
    Timer = {
      # 30 min. The sweep searches a bounded batch and returns, leaving slskd's
      # 50-slot downloader to pull them in the background; 30 min tops that
      # queue back up as batches complete without hammering the network (queuing
      # is free on Soulseek — no rate limit or penalty; the only real constraint
      # is per-peer upload slots, which the sweep's own fan-out already spreads).
      # At ~40 searches/run that drains the ~3.5k backlog over a couple of days
      # of search while downloads follow, and a run that overruns the interval
      # is absorbed by the wrapper's flock.
      OnBootSec = "5min";
      # Required alongside OnBootSec: it counts from system boot, but the user
      # manager starts at login; a login later than the offset would otherwise
      # leave the only elapse point in the past and never fire (see nix-docs.nix).
      OnStartupSec = "5min";
      OnUnitActiveSec = "30min";
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
