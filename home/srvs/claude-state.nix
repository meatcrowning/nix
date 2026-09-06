{ pkgs, lib, ... }:

# Cross-machine sync for the whole of ~/.claude.
#
# This supersedes the old memory-only repo: the scope is now everything the
# user would miss on the other machine — memories, the briefing, plans/,
# file-history/, and session transcripts. The remote is private, and the
# contents are verbatim session records, so they stay private. See
# docs/agents/claude-state-sync.md for the procedure and the failure modes.
#
# Two nix-managed seed files carry the safety argument:
#   gitignore     denylist for secrets and machine-local runtime state.
#   gitattributes merge policy per file shape, so the timer does not wedge on a
#                 conflict.
#
# The tree is much smaller packed than it looks because the transcripts are
# line-oriented text and delta-compress well.

let
  # git for the sync, gh for the credential helper, and the usual coreutils /
  # util-linux / inetutils / gnused helpers for logging, staging, and size
  # checks. The ambient systemd-user PATH cannot be trusted for any of them.
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
    # Generic sync engine, shared with nix-docs.nix.
    "scripts/claude-memory-sync.sh" = {
      source = ./claude-state-files/claude-memory-sync.sh;
      executable = true;
    };
    "scripts/claude-state-premigrate.sh" = {
      source = ./claude-state-files/claude-state-premigrate.sh;
      executable = true;
    };
    # Frontmatter-aware merge driver for the memory store. Premigrate registers
    # it by name so git does not fall back to the repo-wide `*.md merge=union`
    # rule, which would merge structure and silently duplicate frontmatter.
    "scripts/claude-memory-merge.sh" = {
      source = ./claude-state-files/claude-memory-merge.sh;
      executable = true;
    };
    # Seeds copied into the repo on every run, so the denylist and merge policy
    # stay nix-authoritative instead of drifting in an untracked dotfile.
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
        # Backstop on the denylist. Normal ticks move single-digit MB; the cap
        # is above the one-time initial commit and only fires on something odd.
        "CM_SYNC_MAX_MB=250"
      ];
      # Retires the nested claude-memories repo and installs the `ours` merge
      # driver. Must be a Pre step: committing projects/ while its own .git
      # still exists would record a gitlink and sync nothing inside it.
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
      # Required alongside it: OnBootSec counts from system boot, but the user
      # manager starts at login, so a late login would otherwise miss the first
      # tick entirely.
      OnStartupSec = "2min";
      OnUnitActiveSec = "5min";
      # Catch up after the machine was asleep/off rather than waiting a full
      # interval — important on the laptop, which is rarely on for long.
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
