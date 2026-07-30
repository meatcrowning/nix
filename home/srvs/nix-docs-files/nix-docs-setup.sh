#!/bin/sh
# nix-docs-setup.sh — ExecStartPre for nix-docs-sync.service.
#
# Registers the board.md merge driver in docs/'s repo config. This has to live
# outside the .gitattributes seed because a gitattributes rule names a driver by
# a short name only; the command behind that name is repo-local config that no
# file in the tree can carry. Same split, and the same reason, as
# claude-state-premigrate.sh does for merge=claudemd — registered per caller
# because claude-memory-sync.sh is the shared engine and has no opinion about
# either repo's file shapes.
#
# Runs on every tick and is idempotent: a rebuild that moves the driver's store
# path is picked up at the next sync with nothing to redo by hand.
REPO="${CM_SYNC_REPO:-$HOME/nix/docs}"
LOG="${CM_SYNC_LOG:-$HOME/.cache/nix-docs-sync.log}"
DRIVER="${CM_SYNC_MERGE_DRIVER:-$HOME/.config/scripts/board-recent-merge.sh}"

# Not cloned yet: the sync script itself does the first clone, so this is the
# normal first-run state on a new machine and not an error. The next tick, three
# minutes later, finds the repo and registers the driver.
[ -d "$REPO/.git" ] || exit 0

if [ -x "$DRIVER" ]; then
  git -C "$REPO" config merge.boardrecent.driver "$DRIVER %O %A %B %L %P"
  git -C "$REPO" config merge.boardrecent.name \
    "board.md (real 3-way merge; newest side wins a genuine collision)"
else
  # Never leave a registration pointing at a path that no longer exists: git
  # fails the merge outright and wedges the sync for every other file in docs/.
  # Unsetting falls back to the default merge — no worse than before this
  # existed, and it keeps the other files moving.
  git -C "$REPO" config --unset merge.boardrecent.driver 2>/dev/null
  echo "$(date -Is) WARNING: board merge driver missing at $DRIVER" >>"$LOG"
fi

exit 0
