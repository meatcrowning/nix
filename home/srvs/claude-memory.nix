{ pkgs, lib, ... }:

# Cross-machine sync for Claude Code's memory files.
#
# Claude writes one markdown file per memory under
# ~/.claude/projects/<slug>/memory/, plus a MEMORY.md index loaded into context
# every session. Those are per-machine by default, so anything learned on `top`
# was invisible on `book` and vice versa. This makes ~/.claude/projects a git
# repo against a PRIVATE remote and syncs it both ways on a timer.
#
# Both machines get this: `home/` is shared verbatim between `top` and `air`
# via lam.nix + umport, and Fedora Asahi runs systemd the same as NixOS.
#
# Scope is enforced by an ALLOWLIST .gitignore (see claude-memory-files/) — only
# */memory/** is tracked, never the session transcripts sitting in the same tree.
# The script is the interesting part; read its header before changing anything.

{
  xdg.configFile = {
    "scripts/claude-memory-sync.sh" = {
      source = ./claude-memory-files/claude-memory-sync.sh;
      executable = true;
    };
    # Seeds copied into the repo on every run, so the allowlist and the merge
    # policy stay nix-authoritative rather than drifting as hand-edits in an
    # untracked dotfile.
    "scripts/claude-memory-seed/gitignore".source =
      ./claude-memory-files/gitignore;
    "scripts/claude-memory-seed/gitattributes".source =
      ./claude-memory-files/gitattributes;
  };

  systemd.user.services.claude-memory-sync = {
    Unit.Description = "Sync Claude memory files with the private claude-memories repo";
    Service = {
      Type = "oneshot";
      # Pin PATH: the git credential helper is `!gh auth git-credential`, so gh
      # must be resolvable, and the ambient systemd-user PATH cannot be relied
      # on for it. flock comes from util-linux.
      Environment = [
        "PATH=${lib.makeBinPath [
          pkgs.git
          pkgs.gh
          pkgs.coreutils
          pkgs.util-linux
          pkgs.inetutils
        ]}"
      ];
      ExecStart = "%h/.config/scripts/claude-memory-sync.sh";
    };
  };

  systemd.user.timers.claude-memory-sync = {
    Unit.Description = "Periodically sync Claude memory files across machines";
    Timer = {
      # Memory files change whenever a session writes one, which no path unit
      # can watch cheaply (they live in per-project subdirectories that appear
      # over time). A short poll is simpler and the repo is tiny — a run with
      # nothing to do is two git no-ops.
      OnBootSec = "2min";
      OnUnitActiveSec = "5min";
      # Catch up after the machine was asleep/off rather than waiting a full
      # interval — important on the laptop, which is rarely on for long.
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
