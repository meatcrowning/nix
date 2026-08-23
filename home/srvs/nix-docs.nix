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
  # The size cap is the net that gitignore would be elsewhere. The script
  # refuses to commit when the staged total exceeds CM_SYNC_MAX_MB — with no
  # gitignore, that refusal is the ONLY thing standing between a stray large
  # file and a wedged sync. It wedged anyway on 2026-08-03: a 118 MB hermes
  # session export landed in the tree, the tick committed it, and every push
  # after failed on GitHub's 100 MB limit — the timer kept committing locally
  # ("commit is local and safe") while nothing reached the remote. Cap it at
  # 25 MB: the largest file docs legitimately carries (DESIGN.md, 218 KB) is
  # two orders of magnitude below it, and anything over it deserves a human
  # decision, loudly, rather than a silent wedge. (claude-state uses 250 MB —
  # too big here, since GitHub's hard limit is what actually breaks the push.)
  #
  # A gitattributes IS seeded, and it carries exactly one rule. Prose here still
  # merges NORMALLY, not merge=union like the memory store: union is right for a
  # pile of independent one-fact files and wrong for prose, where it silently
  # duplicates paragraphs instead of flagging them. A conflict in a runbook
  # should stop and ask a human, and it still does — logged loudly, retried next
  # tick.
  #
  # The boards are the exception, because each is a store rather than a
  # document: board-watch's agents and the board GUI write them unattended — and
  # an unresolved conflict does not merely flag that file, it aborts the tick and
  # stops docs/ syncing in either direction until someone notices. See the seeded
  # gitattributes and board-recent-merge.sh for the policy (real 3-way merge
  # first, most recent side wins a genuine collision).
  #
  # ONE BOARD PER HOST since 2026-07-30: `docs/board.top.md` and
  # `docs/board.book.md`, each written only by the machine it is named for and
  # carried by the other purely as a backup and a history. His words: "i
  # actually want to change it so neither board on top or air syncs ... i dont
  # want that overwriting ... to overwrite anything i do on air. commits
  # obviously will stay synced." The FILES still sync — this repo is unchanged
  # in what it moves; what changed is that nothing on top writes book's board,
  # so nothing arbitrates between them. The merge rule stays as the net for a
  # hand edit on the wrong machine.
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
          pkgs.gnused          # the size-cap diagnostic pipes through sed
          pkgs.util-linux
          pkgs.inetutils
        ]}"
        "CM_SYNC_REPO=%h/nix/docs"
        "CM_SYNC_REMOTE=https://github.com/meatcrowning/nix-docs.git"
        "CM_SYNC_LOG=%h/.cache/nix-docs-sync.log"
        "CM_SYNC_SEED=%h/.config/scripts/nix-docs-seed"
        "CM_SYNC_LABEL=doc"
        "CM_SYNC_MAX_MB=25"
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
