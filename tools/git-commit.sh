#!/bin/sh
# git-commit.sh — COMMIT THROUGH THIS, never bare `git commit` (AGENTS.md,
# "The index is SHARED"). It is the enforcement half of that rule's second
# clause — "git diff what you are about to commit and confirm every hunk is
# yours" — which until now was prose an agent could skip.
#
# Why it exists: a pathspec commit `git commit -m msg -- f.txt` takes the WHOLE
# working-tree copy of f.txt, so if another minister is mid-edit on that same
# file, its half-finished WIP is swept silently into your commit. That really
# happened: commit 9c1f477 was meant to carry one agent's cards() session-filter
# hunk, but boardwork.py also held another agent's decision-unit WIP in the
# working tree, and the pathspec commit took the whole file. Verified
# empirically: staging only your hunks then `git commit -- f.txt` still commits
# the working tree (both sets of hunks); only an index commit respects your
# selection, and only after the index holds nothing but your own hunks.
#
#   tools/git-commit.sh -m "subject" -- path/one path/two   # hardened pathspec commit
#   tools/git-commit.sh -m "subject" --hunks -- path/one    # commit only your hunks
#
# Default mode:
#   - Refuses a bare / -a commit (which would sweep the shared index).
#   - Always prints the exact diff that will land — the whole working-tree copy
#     of each path, which is precisely what a pathspec commit sweeps in.
#   - REFUSES (exit 1) any path whose uncommitted diff vs HEAD is large enough
#     to plausibly carry more than your one change — that is the smell of
#     another minister's WIP riding along. Escape hatches, in order of safety:
#         --hunks            commit only the hunks you pick, leave theirs behind
#         drop the path      leave that file alone, commit the rest
#         --yes-file <path>  you reviewed the printed diff and accept sweeping
#                            that whole file's working-tree copy
#   This is deliberately a hard gate, not a warn: a false positive costs you one
#   --yes-file (or a --hunks pass), while a missed mixed file costs a commit you
#   cannot cleanly take back. Preflight stays warn-not-fail (a false failure
#   there blocks a rebuild); this script only fronts a commit, which is exactly
#   where the danger lands.
#
# --hunks mode:
#   Interactively `git add -p` the given paths, keeping only the hunks you say
#   are yours, then commit the index. The other minister's WIP stays behind,
#   unstaged in the working tree, exactly as you found it. An index commit is
#   the "bare commit" AGENTS.md warns about, but it is safe ONLY because this
#   mode first asserts the index holds nothing but your own staged hunks; if the
#   shared index already holds another minister's staged content it aborts
#   rather than sweep it.
set -u
usage() { sed -n '1,2p' "$0" >&2; echo "usage: $0 -m MSG [--hunks] [--yes-file PATH]... -- PATH..." >&2; }

msg=""
mode="plain"
yes=""
paths=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --hunks) mode="hunks"; shift ;;
    -m) msg="${2:-}"; shift 2 ;;
    --yes-file) yes="$yes $2"; shift 2 ;;
    --) shift; paths="$paths $*"; break ;;
    -a|-A|--all) echo "ERROR: -a stages everything and sweeps the shared index; forbidden here." >&2; usage; exit 2 ;;
    -*) echo "ERROR: unknown option $1" >&2; usage; exit 2 ;;
    *) paths="$paths $1"; shift ;;
  esac
done

if [ -z "$msg" ]; then echo "ERROR: -m MSG is required." >&2; usage; exit 2; fi
if [ -z "$paths" ]; then echo "ERROR: at least one path is required (never a bare commit)." >&2; usage; exit 2; fi
set -- $paths

# A single large uncommitted change is legitimate; the danger is a change that is
# not entirely yours riding along. These thresholds flag "plausibly more than one
# change" — a heuristic, configurable, and always escapable (--hunks/--yes-file).
MAX_HUNKS="${GIT_COMMIT_MAX_HUNKS:-4}"
MAX_LINES="${GIT_COMMIT_MAX_LINES:-60}"

if [ "$mode" = "hunks" ]; then
  # --- --hunks: commit only the hunks you pick, via the index -----------------
  pre=$(git diff --cached --name-only --diff-filter=d)
  if [ -n "$pre" ]; then
    echo "ERROR: the shared index already holds staged content — a hunk-scoped" >&2
    echo "       commit is an index commit, and this would sweep it. Commit or" >&2
    echo "       unstage that first, then retry. Staged now:" >&2
    printf '  %s\n' $pre >&2
    exit 2
  fi

  echo "=== --hunks: stage the hunks that are YOURS with git add -p ==="
  echo "    (y=this hunk, n=not mine, q=quit). Their WIP stays behind, unstaged."
  git add -p -- "$@"
  rc=$?
  if [ "$rc" -ne 0 ]; then echo "ERROR: git add -p failed." >&2; exit 2; fi

  staged_now=$(git diff --cached --name-only --diff-filter=d)
  if [ -z "$staged_now" ]; then
    echo "ERROR: you staged nothing — nothing to commit. Working tree untouched." >&2
    exit 2
  fi
  # Only our paths may be staged; anything stale in the shared index would get
  # swept by the index commit below.
  bad=0
  for f in $staged_now; do
    in_paths=0
    for p in "$@"; do [ "$f" = "$p" ] && in_paths=1; done
    [ "$in_paths" -eq 1 ] || { echo "ERROR: index holds $f outside the commit set — unwilling to sweep it." >&2; bad=1; }
  done
  [ "$bad" -eq 0 ] || { echo "       Unstage it (git restore --staged), then retry." >&2; exit 2; }

  echo "=== will commit from the index (only your hunks): ==="
  git diff --cached --stat
  echo "=== committing: $msg ==="
  git commit -m "$msg"
  rc=$?
  echo "--- done. Their WIP is still in the working tree (uncommitted, unstaged). ==="
  exit "$rc"
fi

# --- default: hardened pathspec commit -----------------------------------------
diff_full=$(git diff HEAD -- "$@")
if [ -z "$diff_full" ]; then
  echo "ERROR: no working-tree change vs HEAD for the given paths — nothing to commit." >&2
  echo "       (A pathspec commit takes the working-tree copy; there is none here.)" >&2
  exit 2
fi

echo "======================================================================"
echo " COMMITTING (working-tree copy — EVERYTHING below lands in the commit):"
echo "======================================================================"
echo "$diff_full"

# Flag paths whose uncommitted change is large enough to plausibly be mixed work.
flagged=""
for p in "$@"; do
  git cat-file -e HEAD:"$p" 2>/dev/null || continue   # new file: only one author, not the mixed smell
  hunks=$(git diff --unified=0 HEAD -- "$p" | grep -c '^@@')
  churn=$(git diff --numstat HEAD -- "$p" | awk '{s=$1+$2} END{print s+0}')
  ack=0
  for y in $yes; do [ "$y" = "$p" ] && ack=1; done
  if [ "$hunks" -ge "$MAX_HUNKS" ] || [ "$churn" -ge "$MAX_LINES" ]; then
    if [ "$ack" -eq 0 ]; then
      flagged="$flagged $p"
      echo "WARN: $p has $hunks hunk(s), $churn changed line(s) vs HEAD — larger than a focused"
      echo "      single change looks; this is the smell of ANOTHER MINISTER'S WIP riding along."
    fi
  fi
done

if [ -n "$flagged" ]; then
  echo "======================================================================"
  echo " REFUSING — a pathspec commit takes the WHOLE working-tree copy, so this"
  echo " would sweep the other minister's half-finished edits into one commit."
  echo " Do one of:"
  echo "   tools/git-commit.sh -m '$msg' --hunks -- <path>   # commit only YOUR hunks"
  echo "   drop the path / narrow the pathspec                # leave that file alone"
  echo "   add --yes-file <path>                              # reviewed the diff above,"
  echo "                                                     # accept the whole file"
  echo " Flagged:$flagged"
  echo "======================================================================"
  exit 1
fi

echo "=== committing: $msg ==="
git commit -m "$msg" -- "$@"
rc=$?
if [ "$rc" -eq 0 ]; then
  echo "--- pushed? no: remind ---"
  echo "    git pull --rebase && git push origin main"
fi
exit "$rc"
