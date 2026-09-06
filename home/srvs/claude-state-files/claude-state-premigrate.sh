#!/bin/sh
# claude-state-premigrate.sh — make ~/.claude safe for claude-memory-sync.sh to
# treat as a single repo. It runs as ExecStartPre, is idempotent, and becomes a
# no-op after the migration steps below have happened.
#
# ~/.claude/projects used to be its own repo with an allowlist .gitignore. The
# sync now covers the whole of ~/.claude, so that inner repo must go: otherwise
# git would record projects/ as a gitlink and none of its contents would sync.
# `book` cannot be migrated by hand, so the unit has to do it itself.
#
# Nothing is deleted. The inner .git is moved aside, and the old remote remains
# an archive.

REPO="${CM_SYNC_REPO:-$HOME/.claude}"
BRANCH="${CM_SYNC_BRANCH:-main}"
LOG="${CM_SYNC_LOG:-$HOME/.cache/claude-state-sync.log}"

mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
log() { echo "$(date -Is) premigrate: $*"; }

[ -d "$REPO" ] || { log "no $REPO — nothing to do"; exit 0; }

# ---- 1. retire the nested claude-memories repo ------------------------------
if [ -d "$REPO/projects/.git" ]; then
  dest="$HOME/.cache/claude-memories-git-$(date +%Y%m%d-%H%M%S)"
  if mv "$REPO/projects/.git" "$dest"; then
    log "moved the old claude-memories repo aside -> $dest"
    log "  (memory FILES are untouched and are now tracked by this repo;"
    log "   the claude-memories remote keeps its own history as an archive)"
  else
    log "FAILED to move $REPO/projects/.git aside — refusing to continue,"
    log "  because projects/ would be committed as an empty gitlink."
    exit 1
  fi
fi

# The old repo's seeded .gitignore/.gitattributes outlive its .git, and the
# .gitignore was the allowlist. Left in place, it would keep re-creating the
# original bug: everything else synced, and not one transcript did.
for stale in .gitignore .gitattributes; do
  [ -f "$REPO/projects/$stale" ] || continue
  dest="$HOME/.cache/claude-memories-projects$stale-$(date +%Y%m%d-%H%M%S)"
  # Seeded read-only, so mv needs to be allowed to clobber the destination.
  if mv -f "$REPO/projects/$stale" "$dest" 2>/dev/null; then
    log "retired the old allowlist projects/$stale -> $dest"
  else
    log "FAILED to move $REPO/projects/$stale aside — transcripts will NOT sync"
    exit 1
  fi
done

# ---- 2. repo + merge driver -------------------------------------------------
# claude-memory-sync.sh bootstraps the repo itself, but the `ours` merge driver
# has to exist before its first merge. Doing both here keeps the shared script
# generic.
[ -d "$REPO/.git" ] || {
  git -C "$REPO" init -q -b "$BRANCH" || { log "git init failed"; exit 1; }
  log "initialised $REPO"
}

# `ours` is not a built-in: .gitattributes naming it is inert unless the repo
# declares a driver for it, and `true` is the whole implementation.
git -C "$REPO" config merge.ours.driver true

# Same deal for `claudemd`, the frontmatter-aware driver for the memory store:
# if it is missing, git falls back to the `*.md merge=union` rule above and can
# silently duplicate frontmatter. It is registered here because the shared sync
# engine is generic and reused by nix-docs.nix.
DRIVER="${CM_SYNC_MERGE_DRIVER:-$HOME/.config/scripts/claude-memory-merge.sh}"
if [ -x "$DRIVER" ]; then
  git -C "$REPO" config merge.claudemd.driver "$DRIVER %O %A %B %L %P"
  git -C "$REPO" config merge.claudemd.name "Claude memory store (frontmatter-aware)"
else
  # Do not leave a stale registration pointing at a path that no longer exists:
  # git would fail the merge outright and wedge the sync for every other file.
  # Unsetting falls back to union — degraded, but it keeps syncing.
  git -C "$REPO" config --unset merge.claudemd.driver 2>/dev/null
  log "WARNING: merge driver missing at $DRIVER — memory merges fall back to union"
fi

exit 0
