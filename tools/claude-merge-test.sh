#!/usr/bin/env bash
# claude-merge-test.sh — regression test for the claude-state memory merge driver
# (home/srvs/claude-state-files/claude-memory-merge.sh).
#
# WHY: ~/.claude is synced between top and book by an unattended 5-minute timer,
# so a merge that resolves WRONG is never seen by a human at the moment it
# happens. The repo-wide `*.md merge=union` policy merged a memory's frontmatter
# as if it were prose and produced a document with two `description:` keys —
# valid-looking, malformed, silent. This test is what keeps that fixed.
#
# It drives REAL git merges of two divergent branches, the way the two machines
# actually diverge, rather than calling the driver by hand. Run it after ANY edit
# to the driver, .gitattributes' memory rule, or premigrate's registration of it:
#
#   ./tools/claude-merge-test.sh    # 42 assertions; exit 0 = all pass
#
# Runs entirely in a temp repo. Touches nothing in ~/.claude.
set -u
DRIVER="${1:-$(cd "$(dirname "$0")/.." && pwd)/home/srvs/claude-state-files/claude-memory-merge.sh}"
[ -x "$DRIVER" ] || { echo "not executable: $DRIVER" >&2; exit 2; }
T=$(mktemp -d); cd "$T" || exit 1
pass=0; fail=0
ok()   { pass=$((pass+1)); printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want [$3] got [$2])"; fi; }

git init -q -b main .
git config user.email t@t; git config user.name t
git config merge.claudemd.driver "$DRIVER %O %A %B %L %P"
mkdir -p projects/p/memory
printf '**/memory/*.md merge=claudemd\n' > .gitattributes
git add -A && git commit -qm base0

# each case: seed on main, branch off, edit both sides, merge
setup() {  # $1=file $2=base-content
  git checkout -q main
  printf '%s' "$2" > "$1"; git add -A; git commit -qm "seed $1" >/dev/null 2>&1
  git branch -q -f book HEAD
}
diverge() { # $1=file $2=ours $3=theirs
  printf '%s' "$2" > "$1"; git add -A; git commit -qm "top edits $1" >/dev/null 2>&1
  git checkout -q book; printf '%s' "$3" > "$1"; git add -A; git commit -qm "book edits $1" >/dev/null 2>&1
  git checkout -q main
  git merge -q --no-edit book >/dev/null 2>&1; echo "$?"
}

mem() { # $1=modified $2=body   -> a realistic memory file
  printf -- '---\nname: m\ndescription: "a fact"\nmetadata: \n  type: project\n  modified: %s\n---\n\n%s\n' "$1" "$2"
}

echo "=== 1. both dated: NEWER wins, structure intact ==="
F=projects/p/memory/m.md
setup $F "$(mem 2026-07-01T00:00:00.000Z old)"
rc=$(diverge $F "$(mem 2026-07-20T00:00:00.000Z TOPNEW)" "$(mem 2026-07-10T00:00:00.000Z bookold)")
check "merge resolved (rc=0)" "$rc" "0"
check "newer body kept"    "$(grep -c TOPNEW $F)" "1"
check "older body dropped" "$(grep -c bookold $F)" "0"
check "exactly one frontmatter" "$(grep -c '^---$' $F)" "2"
check "exactly one description" "$(grep -c '^description:' $F)" "1"

echo "=== 2. both dated, THEIRS newer (side-independence) ==="
setup $F "$(mem 2026-07-01T00:00:00.000Z old)"
rc=$(diverge $F "$(mem 2026-07-10T00:00:00.000Z topold)" "$(mem 2026-07-20T00:00:00.000Z BOOKNEW)")
check "merge resolved" "$rc" "0"
check "newer (theirs) body kept" "$(grep -c BOOKNEW $F)" "1"
check "one frontmatter" "$(grep -c '^---$' $F)" "2"

echo "=== 3. only theirs dated ==="
setup $F "$(mem 2026-07-01T00:00:00.000Z old)"
undated=$(printf -- '---\nname: m\ndescription: "d"\n---\n\ntopundated\n')
rc=$(diverge $F "$undated" "$(mem 2026-07-20T00:00:00.000Z BOOKDATED)")
check "merge resolved" "$rc" "0"
check "dated side kept" "$(grep -c BOOKDATED $F)" "1"
check "one frontmatter" "$(grep -c '^---$' $F)" "2"

echo "=== 4. NEITHER dated: one frontmatter, both bodies (no loss) ==="
setup $F "$(printf -- '---\nname: m\ndescription: "d"\n---\n\nshared\n')"
rc=$(diverge $F "$(printf -- '---\nname: m\ndescription: "d"\n---\n\nshared\nTOPFACT\n')" \
                "$(printf -- '---\nname: m\ndescription: "d"\n---\n\nshared\nBOOKFACT\n')")
check "merge resolved" "$rc" "0"
check "ours body kept"   "$(grep -c TOPFACT $F)" "1"
check "theirs body kept" "$(grep -c BOOKFACT $F)" "1"
check "STILL one frontmatter" "$(grep -c '^---$' $F)" "2"
check "one description"       "$(grep -c '^description:' $F)" "1"
check "no conflict markers"   "$(grep -c '^<<<<<<<\|^>>>>>>>' $F)" "0"

echo "=== 5. the REAL historical case: union fused two revisions ==="
# what actually happened on top: old allowlist revision vs new state revision
setup $F "$(mem 2026-07-25T23:49:13.057Z 'ALLOWLIST claude-memories')"
rc=$(diverge $F "$(mem 2026-07-25T23:49:13.057Z 'ALLOWLIST claude-memories')" \
                "$(mem 2026-07-28T01:40:11.375Z 'DENYLIST claude-state')")
check "merge resolved" "$rc" "0"
check "one frontmatter (the bug)" "$(grep -c '^---$' $F)" "2"
check "one description (the bug)" "$(grep -c '^description:' $F)" "1"
check "one modified key"          "$(grep -c 'modified:' $F)" "1"
check "newer revision kept"  "$(grep -c 'DENYLIST' $F)" "1"
check "stale revision gone"  "$(grep -c 'ALLOWLIST' $F)" "0"
echo "  --- resolved file ---"; sed 's/^/    /' $F

echo "=== 6. MEMORY.md: distinct additions both survive ==="
I=projects/p/memory/MEMORY.md
setup $I "$(printf -- '- [a](a.md) - aaa\n')"
rc=$(diverge $I "$(printf -- '- [a](a.md) - aaa\n- [t](top.md) - from top\n')" \
                "$(printf -- '- [a](a.md) - aaa\n- [b](book.md) - from book\n')")
check "merge resolved" "$rc" "0"
check "ours line kept"   "$(grep -c 'from top' $I)" "1"
check "theirs line kept" "$(grep -c 'from book' $I)" "1"
check "shared line NOT duplicated" "$(grep -c '](a.md)' $I)" "1"

echo "=== 7. MEMORY.md: same line added twice -> collapsed ==="
setup $I "$(printf -- '- [a](a.md) - aaa\n')"
rc=$(diverge $I "$(printf -- '- [a](a.md) - aaa\n- [n](new.md) - same text\n')" \
                "$(printf -- '- [a](a.md) - aaa\n- [n](new.md) - same text\n')")
check "merge resolved" "$rc" "0"
check "collapsed to one" "$(grep -c '](new.md)' $I)" "1"

echo "=== 8. MEMORY.md: pointer REWRITTEN (top's real dupe) -> newer kept ==="
setup $I "$(printf -- '- [Claude memory sync](cms.md) - allowlist, memories only\n- [z](z.md) - zzz\n')"
rc=$(diverge $I "$(printf -- '- [Claude memory sync](cms.md) - allowlist, memories only\n- [z](z.md) - zzz\n')" \
                "$(printf -- '- [Claude state sync](cms.md) - DENYLIST, all of ~/.claude\n- [z](z.md) - zzz\n')")
check "merge resolved" "$rc" "0"
check "one line for that target" "$(grep -c '](cms.md)' $I)" "1"
check "rewrite kept"  "$(grep -c 'DENYLIST' $I)" "1"
check "stale dropped" "$(grep -c 'allowlist, memories only' $I)" "0"
check "unrelated line untouched" "$(grep -c '](z.md)' $I)" "1"

echo "=== 9. MEMORY.md: headings/blanks/prose pass through ==="
setup $I "$(printf -- '# Index\n\nsome prose\n\n- [a](a.md) - aaa\n\nmore prose\n')"
rc=$(diverge $I "$(printf -- '# Index\n\nsome prose\n\n- [a](a.md) - aaa\n- [t](t.md) - t\n\nmore prose\n')" \
                "$(printf -- '# Index\n\nsome prose\n\n- [a](a.md) - aaa\n- [b](b.md) - b\n\nmore prose\n')")
check "merge resolved" "$rc" "0"
check "heading kept once" "$(grep -c '^# Index' $I)" "1"
check "prose kept" "$(grep -c 'some prose' $I)" "1"
check "trailing prose kept" "$(grep -c 'more prose' $I)" "1"
check "blank lines preserved" "$([ "$(grep -c '^$' $I)" -ge 2 ] && echo yes || echo no)" "yes"

echo "=== 10. unrelated histories (2nd machine's first sync) ==="
rm -rf "$T/u"; mkdir -p "$T/u"; cd "$T/u" || exit 1
git init -q -b main .; git config user.email t@t; git config user.name t
git config merge.claudemd.driver "$DRIVER %O %A %B %L %P"
mkdir -p projects/p/memory; printf '**/memory/*.md merge=claudemd\n' > .gitattributes
printf -- '---\nname: m\ndescription: "d"\nmetadata: \n  modified: 2026-07-20T00:00:00.000Z\n---\n\nTOPONLY\n' > projects/p/memory/m.md
git add -A; git commit -qm top
git checkout -q --orphan other; git rm -rqf .; mkdir -p projects/p/memory
printf '**/memory/*.md merge=claudemd\n' > .gitattributes
printf -- '---\nname: m\ndescription: "d"\nmetadata: \n  modified: 2026-07-26T00:00:00.000Z\n---\n\nBOOKONLY\n' > projects/p/memory/m.md
git add -A; git commit -qm book
git checkout -q main
git merge -q --no-edit --allow-unrelated-histories other >/dev/null 2>&1
check "unrelated merge resolved" "$?" "0"
check "newer kept" "$(grep -c BOOKONLY projects/p/memory/m.md)" "1"
check "one frontmatter" "$(grep -c '^---$' projects/p/memory/m.md)" "2"

printf '\n=== %d passed, %d failed ===\n' "$pass" "$fail"
cd /; rm -rf "$T"
[ "$fail" -eq 0 ]
