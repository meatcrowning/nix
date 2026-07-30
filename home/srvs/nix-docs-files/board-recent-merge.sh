#!/bin/sh
# board-recent-merge.sh — git low-level merge driver for docs/board.md.
#
# WHY THIS EXISTS
#
# docs/ had no .gitattributes at all, so board.md merged with git's default
# 3-way text merge. That is fine right up until both machines touch the same
# lines, and then it is the worst of the three possible outcomes: the merge
# fails, claude-memory-sync.sh aborts the whole tick and exits 1, and NOTHING
# in docs/ syncs in either direction until a human notices. Both machines then
# drift apart while each looks healthy.
#
# board.md is the file where that is guaranteed to happen eventually: it has an
# unattended writer on each machine (board-watch's agents) plus a GUI on each,
# and a five-minute sync window between them. So it needs a policy that always
# resolves, and [his, 2026-07-29] the policy is recency — "which version of the
# board should we use should be determined by which one was the most recent",
# with the standing requirement that top must never simply overwrite book.
#
# TWO STEPS, IN THIS ORDER, AND THE ORDER IS THE POINT:
#
#   1. Try the REAL 3-way merge. Almost every concurrent pair of edits here
#      touches different sections — book appends a LANDED row while top adds a
#      WAITING bullet — and a real merge keeps BOTH. Going straight to
#      last-writer-wins would throw away a side that never actually collided,
#      which is exactly the overwrite he asked to prevent.
#   2. ONLY where the two sides genuinely collide, keep the side whose commit
#      touching this file is more recent, whole. Symmetric: on top the newer
#      side is often book's, on book it is often top's. Neither host is
#      privileged, which is what makes it safe to run unattended on both.
#
# NOTHING IS EVER LOST. Both sides are committed on their own machine before any
# merge happens, so the revision this driver does not keep stays reachable
# forever (`git log --all -p -- docs/board.md`).
#
# THE CONTRACT: git calls us as `driver %O %A %B %L %P` — base, ours, theirs,
# conflict-marker size, pathname. The result must be written to %A. Exit 0 means
# resolved; non-zero means conflict, which for this repo means that wedged sync.
# So every path below ends in exit 0 with a whole, valid file.
O=$1
A=$2
B=$3
P=$5

LOG="${CM_SYNC_LOG:-$HOME/.cache/nix-docs-sync.log}"
log() { echo "$(date -Is) board-merge($P): $*" >>"$LOG" 2>/dev/null; }

# git merge-file writes conflict markers INTO %A when it fails, so keep our
# side aside first — every fallback below needs it back intact.
OURS="$A.board-merge-ours.$$"
cp -f "$A" "$OURS" 2>/dev/null || exit 0

if git merge-file -q -L ours -L base -L theirs "$A" "$O" "$B" 2>/dev/null; then
  # Clean: both sides' edits are in the file and no line was dropped.
  rm -f "$OURS"
  exit 0
fi

cp -f "$OURS" "$A" 2>/dev/null
rm -f "$OURS"

# Genuine collision. Date each side by the last commit that touched this path.
# %ct is the committer date, which for this repo is the moment that machine's
# sync tick ran — up to five minutes after the edit itself, and equally so on
# both hosts, so it orders the two sides correctly even though it is not the
# edit time.
#
# Ours is HEAD. Theirs is the fiddly half: MERGE_HEAD is NOT written yet while
# the low-level drivers run — git writes it only once the merge concludes — so
# reading it here silently yields nothing and every collision fell through to
# the union fallback. FETCH_HEAD is the one that is already on disk, because
# claude-memory-sync.sh fetches and then merges FETCH_HEAD by name. Try both, in
# the order that makes a hand-run `git merge <branch>` work too.
ours_t=$(git log -1 --format=%ct HEAD -- "$P" 2>/dev/null)
theirs_t=
for ref in MERGE_HEAD FETCH_HEAD; do
  git rev-parse -q --verify "$ref" >/dev/null 2>&1 || continue
  theirs_t=$(git log -1 --format=%ct "$ref" -- "$P" 2>/dev/null)
  [ -n "$theirs_t" ] && break
done

if [ -n "$ours_t" ] && [ -n "$theirs_t" ] && [ "$ours_t" -ne "$theirs_t" ] 2>/dev/null; then
  if [ "$theirs_t" -gt "$ours_t" ]; then
    cp -f "$B" "$A" 2>/dev/null
    log "collision - kept THEIRS (newer: $theirs_t > $ours_t)"
  else
    log "collision - kept OURS (newer: $ours_t > $theirs_t)"
  fi
  exit 0
fi

# Neither side could be dated (no MERGE_HEAD — a hand-run `git merge-file`, a
# rebase, a cherry-pick), or both commits share a second. Union instead: it
# keeps too much rather than dropping a side, which is the failure direction
# this file is allowed to have. Duplicated rows are visible on his board and
# trivially removed; a silently deleted answer is not.
git merge-file --union -q -L ours -L base -L theirs "$A" "$O" "$B" 2>/dev/null
log "collision - could not date both sides, union-merged instead"
exit 0
