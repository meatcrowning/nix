#!/usr/bin/env bash
# Remove agent worktrees whose work has already landed on main.
#
# Background: background agent sessions on this repo can't write to the main
# checkout, so each one branches into .claude/worktrees/<name> and lands its
# work by pushing to main. Nothing removes the checkout afterwards, so they
# pile up — each is a full copy of the tree, which is why `grep -r` here
# starts returning every hit three and four times over.
#
# Safe by construction: a worktree is only removed when ALL of these hold, and
# anything that fails a check is reported and left completely alone.
#
#   1. it lives under .claude/worktrees/  (never the main checkout)
#   2. its working tree is clean          (no uncommitted work to lose)
#   3. its branch has no commits missing from origin/main
#
# Check 3 is the one that matters: "already merged" is judged against the
# REMOTE main, not the local one, so a worktree whose commits only exist
# locally is never discarded.
#
#   ./tools/prune-worktrees.sh              # prune
#   ./tools/prune-worktrees.sh --dry-run    # say what it would do
#
# Remote worktree-* branches are reported but NOT deleted — that is a push to
# someone else's view of the repo, so it stays a deliberate one-liner.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

red()  { printf '\033[31m%s\033[0m\n' "$*"; }
grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
ylw()  { printf '\033[33m%s\033[0m\n' "$*"; }

git fetch -q origin 2>/dev/null || ylw "could not reach origin — judging against the last-known origin/main"

removed=0
kept=0

# --list --porcelain so paths with spaces survive; skip the main checkout.
while IFS= read -r line; do
  case "$line" in worktree\ *) wt="${line#worktree }";; *) continue;; esac
  case "$wt" in *"/.claude/worktrees/"*) ;; *) continue;; esac

  branch=$(git -C "$wt" symbolic-ref --quiet --short HEAD 2>/dev/null || echo "")
  name=${wt##*/}

  if [ -n "$(git -C "$wt" status --porcelain 2>/dev/null)" ]; then
    ylw "KEEP  $name — uncommitted changes in the worktree"
    git -C "$wt" status --short | sed 's/^/        /'
    kept=$((kept + 1)); continue
  fi

  unlanded=$(git -C "$wt" log --oneline origin/main..HEAD 2>/dev/null)
  if [ -n "$unlanded" ]; then
    ylw "KEEP  $name — commits not on origin/main:"
    printf '%s\n' "$unlanded" | sed 's/^/        /'
    kept=$((kept + 1)); continue
  fi

  if [ "$DRY" = 1 ]; then
    grn "would remove  $name${branch:+  (branch $branch)}"
  else
    if git worktree remove "$wt" 2>/dev/null; then
      [ -n "$branch" ] && git branch -D "$branch" >/dev/null 2>&1
      grn "removed  $name${branch:+  (branch $branch)}"
    else
      red "FAILED to remove $name — left in place"
      kept=$((kept + 1)); continue
    fi
  fi
  removed=$((removed + 1))
done < <(git worktree list --porcelain)

[ "$DRY" = 1 ] || git worktree prune

stale_remote=$(git branch -r --merged origin/main 2>/dev/null \
  | sed 's/^ *//' | grep '^origin/worktree-' || true)
if [ -n "$stale_remote" ]; then
  echo
  ylw "merged worktree branches still on the remote (delete deliberately):"
  printf '%s\n' "$stale_remote" | sed 's|^origin/|        git push origin --delete |'
fi

echo
if [ "$removed" = 0 ] && [ "$kept" = 0 ]; then
  echo "no agent worktrees — nothing to do"
else
  echo "$removed removed, $kept kept"
fi
