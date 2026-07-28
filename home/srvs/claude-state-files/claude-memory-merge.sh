#!/bin/sh
# claude-memory-merge.sh — git low-level merge driver for Claude's memory store.
#
# WHY THIS EXISTS
#
# `*.md merge=union` was applied to the whole repo, and for a memory file that is
# wrong in the same way it is wrong for JSON — which .gitattributes already
# argues at length for *.json and then missed here. A memory is not a list of
# independent lines; it is a YAML frontmatter block followed by prose. Union
# merged the STRUCTURE: top's first merge fused two revisions of
# claude-memory-sync.md into one document with two `description:` keys and a
# second `---` in the middle of the body. No conflict, no log line, and it reads
# fine if you skim the prose — every future reader silently gets a malformed
# memory. That is the same class of silent failure the whole claude-state widening
# exists to fix.
#
# Union is still exactly right for MEMORY.md, which IS a list of independent
# lines (one per memory) that both machines append to. So the two shapes need two
# strategies, and this one driver covers both — dispatching on the pathname git
# hands it, so .gitattributes needs a single rule and premigrate a single driver
# registration.
#
# THE CONTRACT: git calls us as `driver %O %A %B %L %P` — base, ours, theirs,
# conflict-marker size, pathname. The result must be written to %A. Exit 0 means
# resolved; non-zero means conflict, which for this repo means a WEDGED sync for
# every other file until a human notices. So this script must always resolve.
# Every branch below ends in a structurally valid file, and the fallbacks degrade
# toward "keeps too much" rather than "keeps something broken".
#
# NOTHING IS EVER LOST. Both sides are committed on their own machine before any
# merge happens, so the revision this driver does not keep stays reachable in
# git history forever (`git log --all -p -- <file>`).
O=$1
A=$2
B=$3
P=$5

# Frontmatter runs from the first `---` line to the next one. `modified:` is
# written by Claude Code itself on every save, in UTC ISO-8601 with a Z suffix —
# a fixed-width format, so a plain string compare orders it correctly and we need
# no date parsing in a POSIX shell.
modified_of() {
  awk '
    /^---$/ { n++; if (n == 2) exit; next }
    n == 1 && /^[[:space:]]*modified:[[:space:]]/ {
      sub(/^[[:space:]]*modified:[[:space:]]*/, ""); gsub(/["\r]/, ""); print; exit
    }
  ' "$1"
}

case "$(basename "$P")" in
MEMORY.md)
  # The index: union keeps both machines' new lines, which is the whole point —
  # then collapse what union duplicates so no one has to. Two distinct cases:
  #
  #   exact duplicate line   both machines added the same pointer.
  #   same link target       one machine REWROTE a pointer (top's real merge left
  #                          both "Claude memory sync" describing the retired
  #                          allowlist AND "Claude state sync" describing what
  #                          replaced it, pointing at one file). Keep the last —
  #                          union appends the incoming side after ours, so the
  #                          last occurrence is the rewrite, not the text it
  #                          replaced.
  #
  # Only `](target.md)` pointer lines are touched. Headings, prose and blank
  # lines are passed through untouched, so this cannot reflow the file.
  git merge-file --union -q -L ours -L base -L theirs "$A" "$O" "$B" 2>/dev/null
  awk '
    match($0, /\]\([^)]*\.md\)/) { t = substr($0, RSTART, RLENGTH); last[t] = NR }
    { line[NR] = $0; tgt[NR] = t; t = "" }
    END {
      for (i = 1; i <= NR; i++)
        if (tgt[i] == "" || last[tgt[i]] == i) print line[i]
    }
  ' "$A" >"$A.merged" && mv "$A.merged" "$A"
  exit 0
  ;;
esac

# A memory file: one fact, stated as a document. There is no honest line-wise
# merge of two prose revisions of the same fact, so resolve it as what it is — a
# statement of current truth, where the newer statement supersedes the older.
# Last-writer-wins by the timestamp Claude Code already maintains.
#
# Deterministic and side-independent: both machines compute the same winner from
# the same two timestamps, so neither ends up preferring "its own" version and
# the two cannot ping-pong an edit between them.
ta=$(modified_of "$A")
tb=$(modified_of "$B")

if [ -n "$ta" ] && [ -n "$tb" ]; then
  # Strings, not dates: fixed-width UTC ISO-8601 sorts chronologically. Compared
  # with sort rather than `[ x \> y ]`, which is a bash/ksh extension POSIX test
  # does not define — this script runs under whatever /bin/sh is on two different
  # distros. Ties keep ours: arbitrary but consistent, and a tie means the two are
  # almost certainly identical anyway.
  if [ "$(printf '%s\n%s\n' "$ta" "$tb" | sort | tail -1)" = "$tb" ] \
     && [ "$ta" != "$tb" ]; then
    cat "$B" >"$A"
  fi
  exit 0
elif [ -n "$tb" ]; then
  cat "$B" >"$A"   # only theirs is dated: it has been through a newer writer
  exit 0
elif [ -n "$ta" ]; then
  exit 0
fi

# Neither side is dated — 15 of top's 59 memories predate Claude Code writing
# `modified:`, and any of them that gets edited gains one. With no ordering
# signal, fall back to keeping BOTH bodies under ONE frontmatter: ours' header,
# then a union of the two bodies. Prose may read doubled, which is the trade the
# old policy made everywhere; the difference is the file is still a valid memory
# with a single frontmatter block, so it degrades to "tidy me" rather than
# "silently malformed for every future reader".
fm_of()   { awk '/^---$/ { n++; print; if (n == 2) exit; next } n == 1 { print }' "$1"; }
body_of() { awk 'n >= 2 { print } /^---$/ { n++ }' "$1"; }

for f in "$O" "$A" "$B"; do
  [ -f "$f" ] || : >"$f"
  body_of "$f" >"$f.body"
done
git merge-file --union -q -L ours -L base -L theirs \
  "$A.body" "$O.body" "$B.body" 2>/dev/null
{ fm_of "$A"; cat "$A.body"; } >"$A.merged" && mv "$A.merged" "$A"
rm -f "$O.body" "$A.body" "$B.body"
exit 0
