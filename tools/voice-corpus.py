#!/usr/bin/env python3
"""Pull every prompt HE actually typed out of the Claude Code transcripts.

The corpus behind `docs/agents/his-voice.md`. Claude Code keeps a JSONL per
session under `~/.claude/projects/`, and a transcript holds four kinds of
"user" turn that look alike on the wire — what he typed, tool results fed back,
task notifications, and the prompts agents write for each other (board-watch's
headless `claude -p`, subagent briefs). Only the first is his voice, so the
filter is structural rather than stylistic: filtering by how a line READS would
select for whatever the reader already believed, which is the one mistake this
corpus exists to prevent.

What survives, and why:

  type == user            not an assistant turn
  userType == external    typed at a keyboard, not injected by the harness
  content is a str        a tool result is a LIST of content blocks
  not isSidechain         a subagent's transcript is the agent's words
  promptSource            `typed` / `queued`, or the older entries that predate
                          the field (entrypoint `cli`, origin absent or human);
                          `sdk` is headless, `system` is the harness
  not a /command, not a <system-reminder>, not a pasted file

`~/.claude` syncs both ways between top and book (`home/srvs/claude-state.nix`),
so this reads BOTH machines' history wherever it is run.

Nothing here is written back into `~/nix` — the repo is public and this is a
verbatim record of whatever he was doing. Print it, read it, quote it into the
PRIVATE `docs/`.

    tools/voice-corpus.py                # every prompt, newest first
    tools/voice-corpus.py --stats        # length/shape distribution
    tools/voice-corpus.py --sample 80    # an even spread across the history
    tools/voice-corpus.py --grep toast   # only ones mentioning a word
"""
import argparse
import glob
import json
import os
import random
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.expanduser("~/.claude/projects")


def prompts():
    seen = set()
    out = []
    for f in glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True):
        try:
            fh = open(f, errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"user"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "user" or d.get("userType") != "external":
                    continue
                if d.get("isSidechain"):
                    continue
                text = d.get("message", {}).get("content")
                if not isinstance(text, str):
                    continue
                src = d.get("promptSource")
                origin = (d.get("origin") or {}).get("kind")
                if src in ("sdk", "system", "suggestion_accepted"):
                    continue
                if src is None and origin not in (None, "human"):
                    continue
                if origin not in (None, "human"):
                    continue
                t = text.strip()
                if not t or t.startswith("<") or t.startswith("/"):
                    continue
                # A pasted file or a command's output is not prose he wrote.
                if t.startswith("[Request interrupted") or "\n```" in t[:200]:
                    continue
                if t in seen:
                    continue
                seen.add(t)
                out.append((d.get("timestamp") or "", t))
    out.sort(reverse=True)
    return out


def local(ts):
    """Transcripts stamp UTC; he lives at -08:00. A quote dated a day late is a
    quote he will not recognise, so convert before printing one."""
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return d.astimezone().strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return ts[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--grep", default="")
    ap.add_argument("--min", type=int, default=0, help="only prompts this long")
    ap.add_argument("--max", type=int, default=0)
    a = ap.parse_args()

    ps = prompts()
    if a.grep:
        rx = re.compile(a.grep, re.I)
        ps = [p for p in ps if rx.search(p[1])]
    if a.min:
        ps = [p for p in ps if len(p[1]) >= a.min]
    if a.max:
        ps = [p for p in ps if len(p[1]) <= a.max]

    if a.stats:
        lens = sorted(len(t) for _, t in ps)
        n = len(lens)
        if not n:
            print("nothing matched")
            return 0
        def pct(p):
            return lens[min(n - 1, int(n * p / 100))]
        lower = sum(1 for _, t in ps if t == t.lower())
        oneline = sum(1 for _, t in ps if "\n" not in t)
        q = sum(1 for _, t in ps if t.rstrip().endswith("?"))
        print("prompts: %d" % n)
        print("chars:   p10 %d  median %d  p90 %d  max %d"
              % (pct(10), pct(50), pct(90), lens[-1]))
        print("all-lowercase: %d (%.0f%%)" % (lower, 100.0 * lower / n))
        print("single line:   %d (%.0f%%)" % (oneline, 100.0 * oneline / n))
        print("ends in '?':   %d (%.0f%%)" % (q, 100.0 * q / n))
        return 0

    if a.sample and a.sample < len(ps):
        random.seed(0)          # a stable sample, so two readings agree
        ps = sorted(random.sample(ps, a.sample), reverse=True)

    for ts, t in ps:
        print("=== %s" % local(ts))
        print(t)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
