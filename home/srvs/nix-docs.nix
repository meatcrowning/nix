{ pkgs, lib, ... }:

# Cross-machine sync for ~/nix/docs.
#
# `meatcrowning/nix` is PUBLIC. The working notes under docs/ — plans, roadmaps,
# impact analyses, the air/top library-share runbook — are not for publication,
# but they still need to be on both machines: the whole point of the runbook is
# that `book` pulls it and finishes a job `top` started.
#
# So docs/ is its own git repo against a PRIVATE remote, living inside the
# public checkout and listed in its .gitignore. Deliberately NOT a submodule:
# `git pull` does not update submodule contents, so the other machine would
# read a stale runbook — precisely the friction this exists to remove. On a
# timer, docs/ is simply always current on both ends.
#
# The sync logic is claude-memory-sync.sh reused verbatim: it is already
# parametrized by CM_SYNC_*, already handles unrelated histories, push races
# and offline ticks, and is already proven across these two machines. Only the
# environment differs.
#
# Both machines get this: `home/` is shared verbatim between `top` and `air`
# via lam.nix + umport, and Fedora Asahi runs systemd the same as NixOS.

{
  # NO gitignore in this seed, deliberately. The claude-memory seed installs an
  # ALLOWLIST .gitignore that ignores everything outside */memory/** — pointing
  # docs/ at it would silently untrack every file here. The script copies
  # `$SEED/gitignore` only `[ -f ]`, so omitting it leaves docs/ alone.
  #
  # A gitattributes IS seeded, and it carries exactly one rule. Prose here still
  # merges NORMALLY, not merge=union like the memory store: union is right for a
  # pile of independent one-fact files and wrong for prose, where it silently
  # duplicates paragraphs instead of flagging them. A conflict in a runbook
  # should stop and ask a human, and it still does — logged loudly, retried next
  # tick.
  #
  # board.md is the exception, because it is a store rather than a document:
  # board-watch's agents write it unattended on BOTH machines and the board GUI
  # writes it on both, so two-sided edits are routine — and an unresolved
  # conflict does not merely flag that file, it aborts the tick and stops docs/
  # syncing in either direction until someone notices. See the seeded
  # gitattributes and board-recent-merge.sh for the policy (real 3-way merge
  # first, most recent side wins a genuine collision).
  xdg.configFile = {
    "scripts/nix-docs-seed/gitattributes".source = ./nix-docs-files/gitattributes;

    "scripts/board-recent-merge.sh" = {
      source = ./nix-docs-files/board-recent-merge.sh;
      executable = true;
    };

    # Registers that driver against its deployed path on every tick — a
    # gitattributes rule names a driver, but the command behind the name is
    # repo-local config no file in the tree can carry.
    "scripts/nix-docs-setup.sh" = {
      source = ./nix-docs-files/nix-docs-setup.sh;
      executable = true;
    };
  };

  systemd.user.services.nix-docs-sync = {
    Unit.Description = "Sync ~/nix/docs with the private nix-docs repo";
    Service = {
      Type = "oneshot";
      # Same PATH pinning rationale as claude-memory-sync: the git credential
      # helper is `!gh auth git-credential`, so gh must be resolvable and the
      # ambient systemd-user PATH cannot be relied on for it.
      Environment = [
        "PATH=${lib.makeBinPath [
          pkgs.git
          pkgs.gh
          pkgs.coreutils
          pkgs.util-linux
          pkgs.inetutils
        ]}"
        "CM_SYNC_REPO=%h/nix/docs"
        "CM_SYNC_REMOTE=https://github.com/meatcrowning/nix-docs.git"
        "CM_SYNC_LOG=%h/.cache/nix-docs-sync.log"
        "CM_SYNC_SEED=%h/.config/scripts/nix-docs-seed"
        "CM_SYNC_LABEL=doc"
      ];
      ExecStartPre = "%h/.config/scripts/nix-docs-setup.sh";
      ExecStart = "%h/.config/scripts/claude-memory-sync.sh";
    };
  };

  systemd.user.timers.nix-docs-sync = {
    Unit.Description = "Periodically sync ~/nix/docs across machines";
    Timer = {
      OnBootSec = "3min";
      # MUST accompany OnBootSec in a USER manager. OnBootSec counts from
      # SYSTEM boot, and the user manager only starts at login — so if login is
      # more than 3min after boot, the only elapse point is already in the past
      # when the timer arms and the unit never fires AT ALL. Not theoretical:
      # on `top` 2026-07-28 the manager started 10min after boot and this timer
      # plus claude-state-sync sat dead for 14 hours of uptime, so everything
      # book wrote that evening reached top only after the next reboot — which
      # read, from the desk, as "the board does not sync". OnStartupSec counts
      # from the MANAGER's own start, so a late login still arms a future tick.
      OnStartupSec = "3min";
      OnUnitActiveSec = "5min";
      # Catch up after the machine was asleep/off rather than waiting a full
      # interval — important on the laptop, which is rarely on for long.
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
