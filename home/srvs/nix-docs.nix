{ pkgs, lib, ... }:

# Cross-machine sync for ~/nix/docs.
#
# `meatcrowning/nix` is public, but docs/ is not: the working notes there need
# to be on both machines and stay private, so docs/ is its own git repo against
# a private remote inside the public checkout. It is deliberately not a
# submodule — `git pull` would leave the other machine stale. See
# docs/agents/claude-state-sync.md for the full sync procedure and failure
# modes.
#
# This module reuses claude-memory-sync.sh as the engine and just changes the
# environment: the repo path, remote, size cap, and the merge-policy seed.
#
# Board files are the only special case. Since 2026-07-30 there is one board
# per host (`docs/board.top.md`, `docs/board.book.md`), each written only by
# the machine it names and carried by the other as backup/history. The
# dedicated merge driver keeps an intact merge from aborting the docs sync.

{
  # No gitignore here: the seed for claude-state uses an allowlist, which would
  # silently untrack docs/. The size cap is the backstop instead; anything over
  # 25 MB is a human decision, not a thing to push blindly.
  #
  # The gitattributes seed keeps prose on the normal merge path. The board files
  # are the exception: they are stores, not documents, so the merge driver does
  # a real 3-way merge first and only falls back to recency on a genuine
  # collision. That keeps a board sync from aborting the whole docs tick.
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
      # MUST accompany OnBootSec in a USER manager. OnBootSec counts from system
      # boot, while the user manager starts at login, so OnStartupSec is what
      # keeps a late login from missing the first tick entirely.
      OnStartupSec = "3min";
      OnUnitActiveSec = "5min";
      # Catch up after the machine was asleep/off rather than waiting a full
      # interval — important on the laptop, which is rarely on for long.
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
