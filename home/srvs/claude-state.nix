{ pkgs, lib, ... }:

# Cross-machine sync for the whole of ~/.claude.
#
# Supersedes claude-memory.nix, which synced ~/.claude/projects/*/memory only.
# That scope was too narrow in a way that was invisible until it bit: a memory
# said "the ~/nix contract lives in /home/lam/.claude/orchestrator-briefing.md
# — follow it exactly", the memory synced to `book`, and the briefing did not,
# because it sits one directory ABOVE the old repo root. Nothing errored. Every
# orchestrator dispatch on that machine just quietly ran without the rules.
#
# So the repo root is now ~/.claude itself and the scope is everything the user
# would miss on the other machine — memories, the briefing, plans/, file edit
# history, and the session transcripts themselves, which are the point: a
# session started on `top` can be read on `book`.
#
# PRIVATE, and it must stay that way. This is a verbatim record of whatever was
# on screen during every session — treat the remote as internal documents.
#
# Two files carry the safety argument, both nix-authoritative and re-seeded on
# every run (claude-state-files/):
#   gitignore     DENYLIST — secrets and machine-local runtime state, by name.
#                 The inverse of what it replaced, so read its header: an
#                 allowlist cannot widen by accident and a denylist can.
#   gitattributes merge policy per file shape, so an unattended 5-minute timer
#                 can never wedge on a conflict.
#
# Size is not the problem it looks like: 155M of working tree packs to ~4.3M,
# because transcripts are line-oriented text and delta-compress ~35:1.
#
# Both machines get this: `home/` is shared verbatim between `top` and `air`
# via lam.nix + umport, and Fedora Asahi runs systemd the same as NixOS.

let
  # git for the sync, gh for the credential helper (`!gh auth git-credential`),
  # coreutils/util-linux/inetutils for date+wc+flock+hostname, gnused for the
  # size-cap diagnostic — which is the one that got missed, and it showed up
  # exactly where it hurts: `sed: command not found` on 2026-08-23, in the
  # branch that lists the largest staged paths when a commit is REFUSED for
  # size. The refusal worked; the explanation of what to look at did not. The
  # ambient systemd-user PATH cannot be relied on for any of them.
  syncPath = lib.makeBinPath [
    pkgs.git
    pkgs.gh
    pkgs.coreutils
    pkgs.gnused
    pkgs.util-linux
    pkgs.inetutils
  ];
in
{
  xdg.configFile = {
    # The generic sync engine, shared with nix-docs.nix. Path and filename are
    # unchanged from when this was memory-only, because that module names the
    # deployed path.
    "scripts/claude-memory-sync.sh" = {
      source = ./claude-state-files/claude-memory-sync.sh;
      executable = true;
    };
    "scripts/claude-state-premigrate.sh" = {
      source = ./claude-state-files/claude-state-premigrate.sh;
      executable = true;
    };
    # Frontmatter-aware merge driver for the memory store. Named by
    # .gitattributes (`**/memory/*.md merge=claudemd`) and registered against
    # this deployed path by premigrate on every run — a memory is frontmatter
    # plus prose, and the repo-wide `*.md merge=union` merged its STRUCTURE,
    # producing a file with two `description:` keys and no conflict to notice.
    "scripts/claude-memory-merge.sh" = {
      source = ./claude-state-files/claude-memory-merge.sh;
      executable = true;
    };
    # Seeds copied into the repo on every run, so the denylist and the merge
    # policy stay nix-authoritative rather than drifting as hand-edits in an
    # untracked dotfile.
    "scripts/claude-state-seed/gitignore".source = ./claude-state-files/gitignore;
    "scripts/claude-state-seed/gitattributes".source =
      ./claude-state-files/gitattributes;
  };

  systemd.user.services.claude-state-sync = {
    Unit.Description = "Sync ~/.claude with the private claude-state repo";
    Service = {
      Type = "oneshot";
      Environment = [
        "PATH=${syncPath}"
        "CM_SYNC_REPO=%h/.claude"
        "CM_SYNC_REMOTE=https://github.com/meatcrowning/claude-state.git"
        "CM_SYNC_LOG=%h/.cache/claude-state-sync.log"
        "CM_SYNC_SEED=%h/.config/scripts/claude-state-seed"
        "CM_SYNC_LABEL=file"
        # Backstop on the denylist. A normal tick moves single-digit MB; the
        # one-off first commit of the whole tree is ~155MB, so the cap sits
        # above that and only fires on something genuinely unexpected.
        "CM_SYNC_MAX_MB=250"
      ];
      # Retires the nested claude-memories repo and installs the `ours` merge
      # driver. Idempotent; a no-op after the first run. Must be a Pre step —
      # committing projects/ while its own .git still exists would record a
      # gitlink and sync nothing inside it.
      ExecStartPre = "%h/.config/scripts/claude-state-premigrate.sh";
      ExecStart = "%h/.config/scripts/claude-memory-sync.sh";
    };
  };

  systemd.user.timers.claude-state-sync = {
    Unit.Description = "Periodically sync ~/.claude across machines";
    Timer = {
      # Files change whenever a session writes one, which no path unit can watch
      # cheaply. A short poll is simpler, and a tick with nothing to do is two
      # git no-ops.
      OnBootSec = "2min";
      # Required alongside it: OnBootSec counts from SYSTEM boot but the user
      # manager starts at login, so a login later than 2min after boot leaves
      # the only elapse point in the past and the timer never fires at all.
      # See home/srvs/nix-docs.nix for the 14-hour outage that proved it.
      OnStartupSec = "2min";
      OnUnitActiveSec = "5min";
      # Catch up after the machine was asleep/off rather than waiting a full
      # interval — important on the laptop, which is rarely on for long.
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
