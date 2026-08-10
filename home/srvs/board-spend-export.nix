{ pkgs, lib, host, config, ... }:

# Write this host's hermes spirit spend to ~/nix/docs/spend.<host>.json,
# quarterly-hourly, so the board's spend section can sum BOTH machines' hermes
# rows (apps/board/boardspend.py reads the other host's export beside the local
# ledger). The Claude side of that section already combines — transcripts sync
# through claude-state — but ~/.hermes/state.db does not, so the hermes rows
# were per-host until this unit existed. [his answer, 2026-08-03: build the
# per-host export and sum both.]
#
# THE TRANSPORT IS THE DOCS SYNC, NOT THIS UNIT. The writer (live source at
# apps/board/tools/hermes-spend-export.py — same absolute path on both
# machines, so a script change needs no rebuild) writes spend.<host>.json into
# ~/nix/docs; the existing nix-docs-sync (every 5 min, `git add -A` + commit +
# push) carries it to the other machine like any other doc. This file only
# owns the cadence: 15 minutes, because the figures move on the order of a
# spirit run and the sync is 5 anyway.
#
# WHY A TIMER AND NOT A PATH UNIT: nothing on this desktop writes a file when a
# hermes session ends — the ledger just gains a row — so the timer is the only
# trigger there can be (same reasoning as board-reminder.nix).
#
# The writer is CHEAP when nothing happened: unchanged content means the file
# is not rewritten at all, so a quiet host mints no commits in the docs repo.
{
  systemd.user.services.board-spend-export = {
    Unit.Description = "Export this host's hermes spirit spend to ~/nix/docs";
    Service = {
      Type = "oneshot";
      # Same pinned-PATH shape as board-reminder: the ambient systemd-user PATH
      # reaches nothing. The writer needs no commands of its own — python3 is
      # the full store path in ExecStart, and boardusage (imported for the
      # ledger path + source filter) only reads. The tail names both machines'
      # profile layouts for symmetry with its siblings.
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.coreutils ]}:${config.home.homeDirectory}/.nix-profile/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/usr/bin:/bin"
      ];
      ExecStart = "${pkgs.python3}/bin/python3 /home/lam/nix/apps/board/tools/hermes-spend-export.py";
      TimeoutStartSec = "2min";
    };
  };

  systemd.user.timers.board-spend-export = {
    Unit.Description = "Refresh the hermes spend export quarterly-hourly";
    Timer = {
      OnBootSec = "6min";
      # Required alongside OnBootSec: that one counts from SYSTEM boot, but the
      # user manager starts at login, so a login later than six minutes after
      # boot leaves the only elapse point in the past and the timer never fires
      # at all. See home/srvs/nix-docs.nix for the 14-hour outage that proved it.
      OnStartupSec = "6min";
      OnUnitActiveSec = "15min";
      # So a run that happened while the machine was off is exported at the
      # next boot instead of up to fifteen minutes into it.
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
