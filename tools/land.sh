#!/usr/bin/env bash
# Commit + pull --rebase + push, safely, in a checkout SHARED with other
# agents and the user. This is the four index rules from AGENTS.md ("Git, and
# landing your work") as one command:
#
#   - the commit is built from an explicit pathspec only, so it takes exactly
#     the paths given and leaves everyone else's staged work untouched;
#   - nothing is ever staged (`git add` would touch the shared index);
#   - the sync with origin never stashes, resets or otherwise moves other
#     agents' uncommitted work — a refused rebase means the tree is too dirty,
#     and the commit is left safely local for a later push.
#
#   tools/land.sh [-C dir] -m "subject" [-b "body"] -- <path> [path...]
#
#   -C dir   operate on the repo containing dir (default: cwd) — works for
#            both ~/nix and the nested docs/ repo with no special-casing
#   -m       commit subject (required)
#   -b       commit body (optional)
#
# The Co-Authored-By trailer comes from $LAND_COAUTHOR if set, else the
# default Claude trailer.
#
# Exit: 0 = committed and pushed; 2 = usage error; 1 = anything else, with
# the commit either not made (nothing changed) or made and still local.

set -uo pipefail

usage() {
    printf 'usage: %s [-C dir] -m "subject" [-b "body"] -- <path> [path...]\n' \
        "$(basename "$0")" >&2
    exit 2
}

dir="$PWD"
subject=""
body=""
while getopts 'C:m:b:' opt; do
    case "$opt" in
        C) dir="$OPTARG" ;;
        m) subject="$OPTARG" ;;
        b) body="$OPTARG" ;;
        *) usage ;;
    esac
done
shift $((OPTIND - 1))

[ -n "$subject" ] || usage
[ "$#" -ge 1 ] || usage

# Resolve which repo owns -C's directory. `git -C` from here on, so the
# nested docs/ repo (its own .git inside this checkout) is handled by the
# same code path as the main tree.
repo="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null)" || {
    printf 'land.sh: %s is not inside a git repo\n' "$dir" >&2
    exit 1
}

trailer="${LAND_COAUTHOR:-Co-Authored-By: Claude <noreply@anthropic.com>}"
msg="$subject"$'\n\n'
[ -n "$body" ] && msg+="$body"$'\n\n'
msg+="$trailer"

# The pathspec commit builds from a temporary index: only these paths go in,
# and the shared index is left exactly as other agents had it. If nothing in
# the given paths changed, git refuses — surface that instead of pushing air.
if ! git -C "$repo" commit -m "$msg" -- "$@"; then
    printf 'land.sh: commit failed — nothing changed in the given paths?\n' >&2
    exit 1
fi

# `--git-path` output is relative to the repo, not to our cwd — resolve the
# git dir absolutely or the mid-rebase check silently never fires.
gitdir="$(git -C "$repo" rev-parse --absolute-git-dir)"
mid_rebase() {
    [ -d "$gitdir/rebase-merge" ] || [ -d "$gitdir/rebase-apply" ]
}

# Sync with origin before pushing. Plain pull --rebase refuses when the tree
# holds OTHER agents' uncommitted changes — routine here, and NOT ours to
# stash (--autostash could conflict on pop and strand their work). Fall back
# to fetch + rebase of the committed work, which needs no clean tree beyond
# the paths involved; if even that refuses, try the push anyway — it may
# fast-forward, and the commit is safe locally either way.
sync_with_origin() {
    if git -C "$repo" pull --rebase; then
        return 0
    fi
    # A conflicted rebase leaves the repo mid-rebase: abort, never resolve
    # or force on behalf of other people's work.
    if mid_rebase; then
        git -C "$repo" rebase --abort
        printf 'land.sh: rebase CONFLICTED and was aborted. Your commit is\n' >&2
        printf 'land.sh: local; resolve against origin/main by hand.\n' >&2
        exit 1
    fi
    # Refused before starting (dirty tree). Rebase the committed work off a
    # fresh fetch instead — no working-tree cleanliness needed for untouched
    # paths.
    if git -C "$repo" fetch origin main &&
       git -C "$repo" rebase origin/main; then
        return 0
    fi
    if mid_rebase; then
        git -C "$repo" rebase --abort
        printf 'land.sh: rebase CONFLICTED and was aborted. Your commit is\n' >&2
        printf 'land.sh: local; resolve against origin/main by hand.\n' >&2
        exit 1
    fi
    printf 'land.sh: tree too dirty to rebase; trying the push as-is\n' >&2
    return 1
}

sync_with_origin || true

if git -C "$repo" push origin main; then
    exit 0
fi

# Rejected: someone landed between our sync and the push. One retry.
printf 'land.sh: push rejected, retrying after a rebase\n' >&2
if sync_with_origin && git -C "$repo" push origin main; then
    exit 0
fi

printf 'land.sh: push still rejected. The commit is safely local — the tree\n' >&2
printf 'land.sh: is too dirty to rebase or origin keeps moving; land it by\n' >&2
printf 'land.sh: hand once the tree quiets down.\n' >&2
exit 1
