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
  # No seed files. The claude-memory seed installs an ALLOWLIST .gitignore that
  # ignores everything outside */memory/** — pointing docs/ at it would silently
  # untrack every file here. CM_SYNC_SEED below aims at a directory that has no
  # gitignore/gitattributes, so the script's `[ -f ] && cp` finds nothing and
  # leaves docs/ alone.
  #
  # That also means .md files here merge NORMALLY, not merge=union like the
  # memory store. Union is right for a pile of independent one-fact files and
  # wrong for prose: union-merging a runbook edited on both machines silently
  # duplicates paragraphs instead of flagging them. A conflict here should stop
  # and ask a human, and it does — logged loudly, retried next tick.
  xdg.configFile."scripts/nix-docs-seed/.keep".text = "";

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
      ExecStart = "%h/.config/scripts/claude-memory-sync.sh";
    };
  };

  systemd.user.timers.nix-docs-sync = {
    Unit.Description = "Periodically sync ~/nix/docs across machines";
    Timer = {
      OnBootSec = "3min";
      OnUnitActiveSec = "5min";
      # Catch up after the machine was asleep/off rather than waiting a full
      # interval — important on the laptop, which is rarely on for long.
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
