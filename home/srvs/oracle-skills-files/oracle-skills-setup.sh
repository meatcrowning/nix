#!/bin/sh
# oracle-skills-setup.sh — ExecStartPre for oracle-skills-sync.service.
#
# Registers the recency merge driver in the repo's config. It has to live
# outside the .gitattributes seed because a gitattributes rule names a driver by
# a short name only; the command behind that name is repo-local config that no
# file in the tree can carry. Same split, and the same reason, as
# nix-docs-setup.sh and claude-state-premigrate.sh.
#
# The driver itself is board-recent-merge.sh, reused verbatim: its policy —
# real 3-way merge first, newest side wins a genuine collision — is generic and
# is exactly what a shared skills base wants. It is deployed by
# home/srvs/nix-docs.nix, which lands on both hosts.
#
# Runs on every tick and is idempotent.
REPO="${CM_SYNC_REPO:-$HOME/.local/share/oracle}"
LOG="${CM_SYNC_LOG:-$HOME/.cache/oracle-skills-sync.log}"
DRIVER="${CM_SYNC_MERGE_DRIVER:-$HOME/.config/scripts/board-recent-merge.sh}"

# Not a repo yet: the sync script bootstraps or clones it, so this is the normal
# first-run state and not an error. The next tick registers the driver.
[ -d "$REPO/.git" ] || exit 0

if [ -x "$DRIVER" ]; then
  git -C "$REPO" config merge.recentwins.driver "$DRIVER %O %A %B %L %P"
  git -C "$REPO" config merge.recentwins.name \
    "skills/agents markdown (real 3-way merge; newest side wins a collision)"
else
  # Never leave a registration pointing at a path that no longer exists: git
  # fails the merge outright and wedges the sync for every other file too.
  git -C "$REPO" config --unset merge.recentwins.driver 2>/dev/null
  echo "$(date -Is) WARNING: recency merge driver missing at $DRIVER" >>"$LOG"
fi

exit 0
