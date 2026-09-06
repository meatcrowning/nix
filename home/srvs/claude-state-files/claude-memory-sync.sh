#!/bin/sh
# claude-memory-sync.sh — generic private-repo sync across two machines.
#
# The engine is reused by home/srvs/claude-state.nix for the whole of ~/.claude
# and by home/srvs/nix-docs.nix for ~/nix/docs. It commits local changes, pulls
# remote ones, and leaves the caller to decide the repo path, remote, log, and
# size cap through CM_SYNC_*.
#
# Safety depends on the caller's seed files: a denylist .gitignore for secrets
# and machine-local runtime state, plus .gitattributes for the merge policy.
# The default policy keeps markdown content with union and leaves true
# delete/edit conflicts for a human. Worktree projects are excluded outright.
REPO="${CM_SYNC_REPO:-$HOME/.claude}"
REMOTE="${CM_SYNC_REMOTE:-https://github.com/meatcrowning/claude-state.git}"
BRANCH="${CM_SYNC_BRANCH:-main}"
LOG="${CM_SYNC_LOG:-$HOME/.cache/claude-state-sync.log}"
# MUST be overridden by any other caller: this default seeds ~/.claude's
# DENYLIST .gitignore, which excludes that tree's secrets and runtime state by
# name. Point a different repo at it and it inherits exclusions that mean
# nothing there, while its own secrets go unguarded.
SEED="${CM_SYNC_SEED:-$HOME/.config/scripts/claude-state-seed}"
# Noun for commit messages, so a reused instance doesn't claim to be syncing
# memories.
LABEL="${CM_SYNC_LABEL:-memory file}"
HOST="$(hostname -s 2>/dev/null || hostname)"

mkdir -p "$(dirname "$LOG")"
# Keep the log from growing without bound.
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG")" -gt 262144 ]; then
  tail -c 131072 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
exec >>"$LOG" 2>&1

# Serialize: the timer and a manual run must not interleave git operations.
LOCK="${CM_SYNC_LOCK:-$HOME/.cache/$(basename "$LOG" .log).lock}"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  flock -n 9 || { echo "$(date -Is) another sync is running — skipping"; exit 0; }
fi

log() { echo "$(date -Is) $*"; }

# A missing REPO is the normal first state for a repo that has never synced.
# Clone it instead, but only when the parent directory already exists.
if [ ! -d "$REPO" ]; then
  if [ -d "$(dirname "$REPO")" ] && git clone -q "$REMOTE" "$REPO" 2>/dev/null; then
    log "=== cloned $REMOTE into $REPO ==="
  else
    log "no $REPO — nothing to sync"
    exit 0
  fi
fi
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

# Backstop for a DENYLIST caller (see ~/.claude): `git add -A` is indiscriminate
# and a denylist can widen by accident. If a tick stages far more than it
# should, that is a missing exclusion, not something to push and discover later.
if [ -n "$CM_SYNC_MAX_MB" ]; then
  staged=0
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    n=$(wc -c <"$f" 2>/dev/null) || continue
    staged=$((staged + n))
  done <<EOF
$(git diff --cached --name-only --diff-filter=ACM)
EOF
  if [ "$staged" -gt $((CM_SYNC_MAX_MB * 1048576)) ]; then
    log "REFUSING TO COMMIT: $((staged / 1048576))MB staged, over CM_SYNC_MAX_MB=$CM_SYNC_MAX_MB"
    log "  Something large landed in $REPO that .gitignore does not exclude."
    log "  Look at what it is BEFORE raising the cap — this repo is private but"
    log "  it is still a copy of everything, sent off this machine."
    log "  Largest staged paths:"
    git diff --cached --name-only --diff-filter=ACM | while IFS= read -r f; do
      [ -f "$f" ] && echo "$(wc -c <"$f") $f"
    done | sort -rn | head -5 | sed 's/^/    /'
    git reset -q           # unstage only; the working tree is untouched
    exit 1
  fi
fi

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
    # have content and neither descends from the other, so merge them.
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
