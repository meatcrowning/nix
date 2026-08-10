#!/bin/bash
# git-commit-test.sh — verify tools/git-commit.sh catches the mixed-WIP hazard
# before it lands, and that --hunks commits only its own hunks. Runs in a throw
# away temp repo, never touches the live checkout. Rerun after touching the
# helper or preflight (the preflight check itself is linted by running it).
set -u
REPO="$HOME/nix"
HC="$REPO/tools/git-commit.sh"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
cd "$T" || exit 1
git init -q && git config user.email test@test && git config user.name test
seq 1 40 | sed 's/^/L/' > boardwork.py   # pretend: the swept file
git add boardwork.py && git commit -qm base

# Two changes, far apart: MY hunk at the top, ANOTHER spirit's WIP at bottom.
sed -i '1a cards_session_filter=True' boardwork.py          # mine
sed -i '$a unit_name_prefix="D"' boardwork.py               # theirs

pass=0; fail=0
ok()   { echo "  ok: $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL: $1"; fail=$((fail+1)); }

echo "== 1) default mode must REFUSE the mixed file (env-forced tiny threshold) =="
GIT_COMMIT_MAX_HUNKS=2 GIT_COMMIT_MAX_LINES=5 "$HC" -m "cards: filter" -- boardwork.py >out1.txt 2>&1
rc1=$?
[ "$rc1" -ne 0 ] && grep -q "REFUSING" out1.txt && grep -qi "another spirit" out1.txt \
  && ok "refused mixed file (rc=$rc1)" || bad "did not refuse (rc=$rc1): $(tail -2 out1.txt)"
[ "$(git log --oneline | wc -l)" -eq 1 ] && ok "no commit landed" || bad "a commit landed"

echo "== 2) --yes-file acknowledges and commits the whole working-tree copy =="
GIT_COMMIT_MAX_HUNKS=2 GIT_COMMIT_MAX_LINES=5 "$HC" -m "cards: filter" --yes-file boardwork.py -- boardwork.py >out2.txt 2>&1
rc2=$?
[ "$rc2" -eq 0 ] && git show HEAD:boardwork.py | grep -q cards_session_filter \
  && ok "yes-file commits (rc=$rc2; mine landed)" || bad "yes-file failed (rc=$rc2): $(tail -2 out2.txt)"
[ "$(git log --oneline | wc -l)" -eq 2 ] && ok "one commit landed" || bad "commit count wrong: $(git log --oneline|wc -l)"
# NOTE: this did sweep both, by explicit ack; rebuild base for the hunks test.

echo "== 3) --hunks commits ONLY my hunk, leaves theirs behind =="
git reset -q --hard HEAD~1    # back to base, discarding the --yes-file commit
sed -i '1a cards_session_filter=True' boardwork.py
sed -i '$a unit_name_prefix="D"' boardwork.py
# feed git add -p: y (my top hunk) then n (their bottom hunk)
printf 'y\nn\n' | "$HC" -m "cards: filter" --hunks -- boardwork.py >out3.txt 2>&1
head_has_mine=$(git show HEAD:boardwork.py | grep -c cards_session_filter)
head_has_theirs=$(git show HEAD:boardwork.py | grep -c unit_name_prefix)
wt_has_theirs=$(grep -c unit_name_prefix boardwork.py)
[ "$head_has_mine" -ge 1 ] && [ "$head_has_theirs" -eq 0 ] \
  && ok "HEAD has my hunk, not theirs" || bad "HEAD: mine=$head_has_mine theirs=$head_has_theirs"
[ "$wt_has_theirs" -ge 1 ] && ok "their WIP still in working tree" || bad "their WIP lost"

echo "== 4) rejects bare / -a / no -m / empty diff =="
"$HC" -a -m x -- boardwork.py >/dev/null 2>&1 && bad "-a not rejected" || ok "rejects -a"
"$HC" -- boardwork.py >/dev/null 2>&1 && bad "no -m not rejected" || ok "rejects missing -m"
"$HC" -m x >/dev/null 2>&1 && bad "no paths not rejected" || ok "rejects missing paths"
git reset -q --hard HEAD
"$HC" -m x -- boardwork.py >/dev/null 2>&1 && bad "empty diff not rejected" || ok "rejects empty diff"

echo "== 5) repeated -m are paragraphs, not last-one-wins =="
# The bug: a subject + body commit landed with the BODY as its subject line.
printf 'another line\n' >> boardwork.py
"$HC" -m "subj: the short one" -m "the why, on its own line." \
      -m "Co-Authored-By: X <x@y>" --yes-file boardwork.py -- boardwork.py >out5.txt 2>&1
[ "$(git log -1 --format=%s)" = "subj: the short one" ] \
  && ok "the subject is the FIRST -m" || bad "subject is $(git log -1 --format=%s)"
git log -1 --format=%b | grep -q "the why, on its own line." \
  && ok "the second -m is the body" || bad "body missing: $(git log -1 --format=%b)"
git log -1 --format=%b | grep -q "^Co-Authored-By: X" \
  && ok "the third is the trailer" || bad "trailer missing"
grep -q "committing: subj: the short one ===$" out5.txt \
  && ok "the banner shows the subject alone" || bad "banner: $(grep committing: out5.txt)"

echo "== 6) preflight still passes (lint) and exits 0 on the live tree =="
if timeout 120 "$REPO/tools/preflight.sh" >/tmp/pf-valac.log 2>&1; then
  ok "preflight exits 0"
else
  echo "  preflight exit $? (read-only on live tree; not expected to fail here)" 
  bad "preflight failed: $(tail -5 /tmp/pf-valac.log)"
fi

echo "----"
echo "PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
