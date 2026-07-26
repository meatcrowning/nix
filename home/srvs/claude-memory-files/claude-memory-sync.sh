#!/bin/sh
# claude-memory-sync.sh — keep Claude's memory files in sync across machines.
#
# Claude Code writes one markdown file per memory under
# ~/.claude/projects/<project-slug>/memory/, plus a MEMORY.md index that is
# loaded into context every session. Those memories are per-machine by default,
# so anything learned on `top` was invisible on `book` and vice versa. This
# script makes ~/.claude/projects itself a git repo pointed at a PRIVATE remote
# and syncs it both ways on a timer.
#
# The repo is IN PLACE — no copying. Claude writes a memory, the next sync run
# picks it up. Deployed to ~/.config/scripts by home/srvs/claude-memory.nix and
# driven by the claude-memory-sync.timer user unit.
#
# SAFETY — ~/.claude/projects also holds every session transcript, which is
# large and full of whatever was on screen at the time. Those must never leave
# the machine, so .gitignore is an ALLOWLIST: ignore everything, then re-include
# only */memory/**. Adding a project or a stray file can therefore never widen
# what gets pushed; only a deliberate .gitignore edit can. Worktree projects
# (*--claude-worktrees-*) are excluded outright — they die with the worktree.
#
# CONFLICTS — .gitattributes marks *.md as `merge=union`, so when both machines
# edit the same memory git keeps BOTH sides' lines instead of failing. For a
# memory store, duplicated text is a trivially fixable outcome and a lost memory
# is not, so union is the right trade. That makes content conflicts impossible;
# only a delete-on-one-side/edit-on-the-other tree conflict can still stop a
# merge, and that is left for a human (logged loudly, retried next tick).
#
# The CM_SYNC_* overrides exist so the script can be exercised against a
# throwaway repo in a test — and, since the logic here is generic
# "keep one private repo in sync across two machines", so a SECOND caller can
# reuse it wholesale. home/srvs/nix-docs.nix does exactly that for ~/nix/docs;
# see the note on CM_SYNC_SEED below before adding a third.
REPO="${CM_SYNC_REPO:-$HOME/.claude/projects}"
REMOTE="${CM_SYNC_REMOTE:-https://github.com/meatcrowning/claude-memories.git}"
BRANCH="${CM_SYNC_BRANCH:-main}"
LOG="${CM_SYNC_LOG:-$HOME/.cache/claude-memory-sync.log}"
# MUST be overridden by any other caller: this default seeds the ALLOWLIST
# .gitignore, which ignores everything except */memory/**. Point a different
# repo at it and every file in that repo silently stops being tracked.
SEED="${CM_SYNC_SEED:-$HOME/.config/scripts/claude-memory-seed}"
# Noun for commit messages, so a reused instance doesn't claim to be syncing
# memories.
LABEL="${CM_SYNC_LABEL:-memory file}"
HOST="$(hostname -s 2>/dev/null || hostname)"

mkdir -p "$(dirname "$LOG")"
# Keep the log from growing without bound (it runs every few minutes forever).
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG")" -gt 262144 ]; then
  tail -c 131072 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
exec >>"$LOG" 2>&1

# Serialize: the timer and a manual run must not interleave git operations.
LOCK="$HOME/.cache/claude-memory-sync.lock"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  flock -n 9 || { echo "$(date -Is) another sync is running — skipping"; exit 0; }
fi

log() { echo "$(date -Is) $*"; }

[ -d "$REPO" ] || { log "no $REPO — nothing to sync"; exit 0; }
cd "$REPO" || exit 0

# ---- one-time bootstrap -----------------------------------------------------
if [ ! -d "$REPO/.git" ]; then
  log "=== bootstrapping $REPO ==="
  git init -q -b "$BRANCH" . || { log "git init failed"; exit 1; }
fi

# Always (re)install the allowlist + merge policy from the nix-managed seed, so
# a change to either ships with a rebuild instead of needing a manual edit here.
for f in gitignore gitattributes; do
  [ -f "$SEED/$f" ] && cp -f "$SEED/$f" "$REPO/.$f"
done

git remote get-url origin >/dev/null 2>&1 || git remote add origin "$REMOTE"
# Keep the URL authoritative — if the seed changes it, follow.
[ "$(git remote get-url origin)" = "$REMOTE" ] || git remote set-url origin "$REMOTE"

# ---- 1. commit whatever this machine changed --------------------------------
git add -A
if git diff --cached --quiet; then
  :
else
  n=$(git diff --cached --name-only | wc -l | tr -d ' ')
  git -c user.name="claude-memory-sync" \
      -c user.email="claude-memory-sync@$HOST" \
      commit -q -m "sync($HOST): $n $LABEL(s)" \
    && log "committed $n file(s)"
fi

# ---- 2. take in the other machine's changes ---------------------------------
if git fetch -q origin "$BRANCH" 2>/dev/null; then
  if [ -n "$(git rev-parse -q --verify FETCH_HEAD)" ]; then
    # Unrelated histories on a second machine's first run: both sides already
    # have memories and neither descends from the other. Union-merge them.
    if git merge-base --is-ancestor FETCH_HEAD HEAD 2>/dev/null; then
      :   # already up to date with the remote
    elif git merge -q --no-edit --allow-unrelated-histories FETCH_HEAD 2>/dev/null; then
      log "merged remote changes"
    else
      git merge --abort 2>/dev/null
      log "MERGE CONFLICT — could not auto-merge origin/$BRANCH."
      log "  Where .gitattributes marks the content merge=union (the memory"
      log "  store does), content conflicts cannot happen, so this is a file"
      log "  deleted on one machine and edited on the other. Elsewhere (docs)"
      log "  it may simply be the same lines edited twice."
      log "  Resolve by hand in $REPO; the timer will retry meanwhile."
      exit 1
    fi
  fi
else
  log "fetch failed (offline, or the remote does not exist yet) — will retry"
fi

# ---- 3. publish -------------------------------------------------------------
# Nothing to push if HEAD has no commits yet.
git rev-parse -q --verify HEAD >/dev/null 2>&1 || { log "no commits yet"; exit 0; }

# Skip the network round-trip entirely when the remote already has our HEAD —
# most ticks have nothing to do, and a quiet log makes the real events visible.
if [ "$(git rev-parse HEAD)" = "$(git rev-parse -q --verify "refs/remotes/origin/$BRANCH" 2>/dev/null)" ]; then
  log "up to date"
elif git push -q -u origin "$BRANCH" 2>/dev/null; then
  log "pushed"
elif git fetch -q origin "$BRANCH" 2>/dev/null \
     && git merge -q --no-edit --allow-unrelated-histories FETCH_HEAD 2>/dev/null \
     && git push -q -u origin "$BRANCH" 2>/dev/null; then
  log "pushed after re-merge (raced with the other machine)"
else
  git merge --abort 2>/dev/null
  log "push failed — commit is local and safe; will retry next tick"
  exit 1
fi
