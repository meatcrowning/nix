#!/bin/sh
# claude-state-premigrate.sh — make ~/.claude safe for claude-memory-sync.sh to
# treat as a single repo. Runs as ExecStartPre on every tick; idempotent, and a
# no-op once both steps below have happened.
#
# WHY THIS EXISTS
#
# ~/.claude/projects used to be its own git repo (the claude-memories remote,
# an ALLOWLIST that tracked only */memory/**). The sync now covers the whole of
# ~/.claude, transcripts included, so that inner repo has to go: git would
# otherwise record projects/ as a gitlink — a bare commit hash — and not one
# byte of what is inside it would ever reach the other machine. The failure is
# silent, which is exactly how the orchestrator briefing went missing in the
# first place.
#
# `book` cannot be migrated by hand (it is a laptop, frequently off and off-LAN),
# so this has to be something the unit does for itself on first run there.
#
# NOTHING IS DELETED. The inner .git is MOVED aside, and the claude-memories
# remote still holds the full memory history — this repo starts fresh, but no
# history is destroyed on either side.

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
# .gitignore is the ALLOWLIST — `*`, re-include only `*/memory/**`. A nested
# .gitignore still applies to its own subtree in the OUTER repo, so leaving it
# there quietly reproduced the exact bug this change exists to fix: everything
# else synced and not one transcript did. Caught only because the first run was
# checked file-by-file; `git add -A` reports nothing about what it skipped.
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
# has to exist BEFORE its first `git merge`, and the script has no hook for
# that. Doing both here keeps the shared script generic.
[ -d "$REPO/.git" ] || {
  git -C "$REPO" init -q -b "$BRANCH" || { log "git init failed"; exit 1; }
  log "initialised $REPO"
}

# `ours` is not a built-in: .gitattributes naming it is inert unless the repo
# declares a driver for it, and `true` is the whole implementation (exit 0,
# leaving the target file — our version — in place).
git -C "$REPO" config merge.ours.driver true

exit 0
