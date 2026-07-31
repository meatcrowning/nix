#!/usr/bin/env bash
# board-merge-test.sh — end-to-end test for the docs/ board merge policy.
#
# There is one board per host since 2026-07-30 (`board.top.md`, `board.book.md`)
# and each is written only by its own machine, so a genuine two-sided edit is
# now rare rather than routine — the driver is the net for one anyway, and the
# scenarios below are what happens when it fires.
#
# Exercises home/srvs/nix-docs-files/board-recent-merge.sh the way git actually
# calls it: a throwaway repo, two branches standing in for `top` and `book`, and
# a real `git merge`. Re-run it after touching the driver, the seeded
# gitattributes, or the registration in nix-docs-setup.sh — a missing
# registration makes the rule INERT with no error, which is the failure this
# whole test exists to catch.
#
#   ./tools/board-merge-test.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVER="$HERE/../home/srvs/nix-docs-files/board-recent-merge.sh"
ATTRS="$HERE/../home/srvs/nix-docs-files/gitattributes"
SETUP="$HERE/../home/srvs/nix-docs-files/nix-docs-setup.sh"

pass=0 fail=0
ok()   { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
bad()  { fail=$((fail + 1)); printf '  FAIL %s\n' "$1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1"; printf '       want: %s\n       got:  %s\n' "$3" "$2"; fi; }

[ -x "$DRIVER" ] || { echo "driver not executable: $DRIVER"; exit 1; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/board-merge-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
export CM_SYNC_LOG="$TMP/sync.log"

# A repo shaped like docs/: the seeded gitattributes, the driver registered the
# way nix-docs-setup.sh registers it.
setup_repo() {
  rm -rf "$TMP/repo"; mkdir -p "$TMP/repo"; cd "$TMP/repo" || exit 1
  git init -q -b main .
  git config user.name  tester
  git config user.email tester@example.invalid
  cp "$ATTRS" .gitattributes
  CM_SYNC_REPO="$TMP/repo" CM_SYNC_MERGE_DRIVER="$DRIVER" "$SETUP"
}

# Commit $2 as the content of $1 with committer date $3 (epoch seconds), so the
# driver's recency comparison has something deterministic to read.
commit_at() {
  printf '%s' "$2" >"$1"
  GIT_AUTHOR_DATE="@$3 +0000" GIT_COMMITTER_DATE="@$3 +0000" \
    git commit -q -a -m "$1 @ $3"
}

BASE=$'# Board\n\n## IN FLIGHT\n\nrow one\n\n## WAITING\n\nbullet one\n\n## LANDED\n\nlanded one\n'

echo "== registration =="
setup_repo
check "driver is registered by nix-docs-setup.sh" \
  "$(git config --get merge.boardrecent.driver | grep -c "$DRIVER")" "1"
check "board.top.md carries merge=boardrecent" \
  "$(git check-attr merge -- board.top.md | awk '{print $NF}')" "boardrecent"
check "board.book.md carries merge=boardrecent" \
  "$(git check-attr merge -- board.book.md | awk '{print $NF}')" "boardrecent"
check "the pre-split board.md still does (old history merges)" \
  "$(git check-attr merge -- board.md | awk '{print $NF}')" "boardrecent"
check "a prose doc does NOT (it still conflicts loudly for a human)" \
  "$(git check-attr merge -- runbook.md | awk '{print $NF}')" "unspecified"
# The reason the rule is three named lines and not `board*.md`: this file is
# prose about the watcher and must still stop and ask a human.
check "agents/board-watch.md is prose, NOT a board" \
  "$(git check-attr merge -- agents/board-watch.md | awk '{print $NF}')" "unspecified"

echo "== 1. non-overlapping edits: BOTH sides survive, nothing overwritten =="
setup_repo
printf '%s' "$BASE" >board.top.md; git add -A
GIT_AUTHOR_DATE="@1000 +0000" GIT_COMMITTER_DATE="@1000 +0000" git commit -q -m base
git branch -q book
# top edits WAITING; book edits LANDED. Book's commit is NEWER on purpose — a
# naive last-writer-wins would drop top's bullet here, and must not.
commit_at board.top.md "${BASE/bullet one/bullet one
- top added this}" 2000
git checkout -q book
commit_at board.top.md "${BASE/landed one/landed one
| abc123 | book added this |}" 3000
git checkout -q main
git fetch -q . book && git merge -q --no-edit FETCH_HEAD >/dev/null 2>&1
check "merge resolved" "$?" "0"
check "top's edit survived a NEWER book commit" "$(grep -c 'top added this' board.top.md)" "1"
check "book's edit survived" "$(grep -c 'book added this' board.top.md)" "1"
check "no conflict markers" "$(grep -c '^<<<<<<<\|^>>>>>>>' board.top.md)" "0"

echo "== 2. genuine collision, THEIRS newer: theirs wins =="
setup_repo
printf '%s' "$BASE" >board.top.md; git add -A
GIT_AUTHOR_DATE="@1000 +0000" GIT_COMMITTER_DATE="@1000 +0000" git commit -q -m base
git branch -q book
commit_at board.top.md "${BASE/row one/row one - TOP VERSION}" 2000
git checkout -q book
commit_at board.top.md "${BASE/row one/row one - BOOK VERSION}" 3000
git checkout -q main
git fetch -q . book && git merge -q --no-edit FETCH_HEAD >/dev/null 2>&1
check "merge resolved" "$?" "0"
check "kept the newer (book) side" "$(grep -c 'BOOK VERSION' board.top.md)" "1"
check "dropped the older (top) side" "$(grep -c 'TOP VERSION' board.top.md)" "0"
check "no conflict markers" "$(grep -c '^<<<<<<<\|^>>>>>>>' board.top.md)" "0"
check "the collision is logged" "$(grep -c 'kept THEIRS' "$CM_SYNC_LOG")" "1"

echo "== 3. genuine collision, OURS newer: ours wins (symmetric) =="
setup_repo
printf '%s' "$BASE" >board.top.md; git add -A
GIT_AUTHOR_DATE="@1000 +0000" GIT_COMMITTER_DATE="@1000 +0000" git commit -q -m base
git branch -q book
commit_at board.top.md "${BASE/row one/row one - TOP VERSION}" 4000
git checkout -q book
commit_at board.top.md "${BASE/row one/row one - BOOK VERSION}" 3000
git checkout -q main
git fetch -q . book && git merge -q --no-edit FETCH_HEAD >/dev/null 2>&1
check "merge resolved" "$?" "0"
check "kept the newer (top) side" "$(grep -c 'TOP VERSION' board.top.md)" "1"
check "dropped the older (book) side" "$(grep -c 'BOOK VERSION' board.top.md)" "0"

echo "== 4. the losing side is still recoverable from history =="
check "the dropped revision is reachable" \
  "$(git log --all -p -- board.top.md | grep -c 'BOOK VERSION')" "1"

echo "== 5. undatable sides fall back to union, never to a wedged sync =="
setup_repo
printf '%s' "$BASE" >board.top.md
printf '%s' "${BASE/row one/row one - TOP VERSION}" >ours
printf '%s' "${BASE/row one/row one - BOOK VERSION}" >theirs
# No MERGE_HEAD: the driver cannot date either side.
"$DRIVER" board.top.md ours theirs 7 board.top.md
check "driver still exits 0" "$?" "0"
check "union kept BOTH sides rather than losing one" \
  "$(grep -c 'TOP VERSION\|BOOK VERSION' ours)" "2"
check "the fallback is logged" "$(grep -c 'union-merged instead' "$CM_SYNC_LOG")" "1"

echo "== 6. a prose doc still conflicts (policy unchanged for runbooks) =="
setup_repo
printf 'para\n' >runbook.md; git add -A
GIT_AUTHOR_DATE="@1000 +0000" GIT_COMMITTER_DATE="@1000 +0000" git commit -q -m base
git branch -q book
commit_at runbook.md $'para top\n' 2000
git checkout -q book
commit_at runbook.md $'para book\n' 3000
git checkout -q main
git fetch -q . book && git merge -q --no-edit FETCH_HEAD >/dev/null 2>&1
check "a hand-written doc still stops and asks a human" "$?" "1"
git merge --abort 2>/dev/null

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
