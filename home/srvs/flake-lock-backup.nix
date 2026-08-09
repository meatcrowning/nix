{ pkgs, lib, ... }:

# Rolling backups of the flake lock file (~/nix/flake.lock).
#
# The lock file is the one file in this repo whose content is derived — a
# `nix flake update` (or `sudo rebuild-top --upgrade`) rewrites it wholesale,
# and the previous lock is gone unless something kept it. This snapshots the
# file into a rotating backup directory whenever it changes, keeping the last
# KEEP copies (timestamped filenames, oldest pruned) under
# ~/.local/state/flake-lock-backup/ — machine-local state, outside the git
# tree, nothing that syncs to the other host.
#
# TWO TRIGGERS, and both are needed (the same pairing board-watch.nix and
# sort-downloads.nix use):
#   - a `path` unit on the FILE itself, so a lock rewrite is captured within
#     seconds of landing. Measured for board.md: PathChanged fires on an
#     atomic replace, which is exactly how git and nix write the lock.
#   - a `timer`, the backstop for rewrites that happened while logged out (a
#     path unit sees nothing then) or that arrived while the service was
#     already running (a path unit does not queue).
#
# A run is cheap when nothing changed: the script compares against the newest
# existing backup and exits without writing when they are identical, so the
# half-hourly timer tick costs one cmp. The service itself is a fast oneshot.
#
# Both machines, verbatim: this is home/, so it deploys to top AND book with
# no host-specific branch — the file paths are the same on both, and the
# backup directory is per-machine state by construction.

{
  xdg.configFile."scripts/flake-lock-backup.sh" = {
    source = ./flake-lock-backup-files/flake-lock-backup.sh;
    executable = true;
  };

  systemd.user.services.flake-lock-backup = {
    Unit = {
      Description = "Snapshot ~/nix/flake.lock into a rotating backup directory";
      # A lock rewrite is a single event, not a burst, so the default start
      # limit is fine. The script is a fast oneshot; there is nothing to spin.
      StartLimitIntervalSec = 60;
      StartLimitBurst = 6;
    };
    Service = {
      Type = "oneshot";
      # The script needs coreutils (ls, sort, tail, cp, rm, date) and diffutils
      # (cmp). Pinned, like the other units here, so nothing depends on the
      # ambient systemd-user PATH.
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.coreutils pkgs.diffutils ]}"
      ];
      ExecStart = "${pkgs.bash}/bin/bash %h/.config/scripts/flake-lock-backup.sh";
      TimeoutStartSec = "1min";
    };
  };

  systemd.user.paths.flake-lock-backup = {
    Unit.Description = "Watch ~/nix/flake.lock for rewrites to snapshot";
    Path.PathChanged = "%h/nix/flake.lock";
    Install.WantedBy = [ "default.target" ];
  };

  systemd.user.timers.flake-lock-backup = {
    Unit.Description = "Backstop snapshot of ~/nix/flake.lock";
    Timer = {
      OnBootSec = "3min";
      # Required alongside OnBootSec: that one counts from SYSTEM boot but the
      # user manager starts at login, so a login later than three minutes after
      # boot leaves the only elapse point in the past and the timer never fires
      # at all. See home/srvs/nix-docs.nix for the 14-hour outage that proved
      # it.
      OnStartupSec = "3min";
      # The path unit handles live rewrites; the timer only needs to catch
      # logged-out ones, so half an hour is a fine worst case.
      OnUnitActiveSec = "30min";
      # A rewrite that happened while the machine was off is noticed at the
      # next boot instead of up to thirty minutes into it.
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
