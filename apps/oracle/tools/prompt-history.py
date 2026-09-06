#!/usr/bin/env python3
"""Read-only search and statistics over his typed prompt history.

Protocol: one JSON object on stdin, one JSON object on stdout.  The caller
passes the canonical Claude transcript and Chatter session roots as argv.  No
index is written: this deliberately reads the real records each call, keeping
the feature private, current, and incapable of changing either history.
"""
import collections
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

MAX_LIMIT = 40
EXCERPT = 900
STOP_WORDS = frozenset("""about after again all also and any are as at be been but by can
could do does for from get give got had has have how i if in into is it its just
like me more my not of on or please so that the then them this to up was we what
when where which who why will with would you your""".split())


def stamp(value):
    """Return UTC seconds for an ISO transcript stamp or a unix session stamp."""
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                   .timestamp())
    except (TypeError, ValueError):
        return 0


def iso(value):
    if not value:
        return ""
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def claude_prompts(root):
    """Mirror voice-corpus.py's structural definition of a typed prompt."""
    seen = set()
    try:
        paths = Path(root).glob("**/*.jsonl")
    except OSError:
        return []
    out = []
    for path in paths:
        try:
            lines = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with lines:
            for line in lines:
                if '"user"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("type") != "user" or row.get("userType") != "external":
                    continue
                if row.get("isSidechain"):
                    continue
                text = row.get("message", {}).get("content")
                if not isinstance(text, str):
                    continue
                src = row.get("promptSource")
                origin = (row.get("origin") or {}).get("kind")
                if src in ("sdk", "system", "suggestion_accepted"):
                    continue
                if src is None and origin not in (None, "human"):
                    continue
                if origin not in (None, "human"):
                    continue
                text = text.strip()
                if (not text or text.startswith("<") or text.startswith("/")
                        or text.startswith("[Request interrupted")
                        or "\n```" in text[:200] or text in seen):
                    continue
                seen.add(text)  # synced transcript copies must not double-count
                out.append({"source": "claude", "text": text,
                            "ts": stamp(row.get("timestamp"))})
    return out


def chatter_prompts(root):
    out = []
    try:
        paths = Path(root).glob("*.json")
    except OSError:
        return out
    for path in paths:
        try:
            session = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(session, dict):
            continue
        title = str(session.get("title") or path.stem)
        sid = str(session.get("id") or path.stem)
        for turn in session.get("turns", []):
            if not isinstance(turn, dict) or not turn.get("isUser"):
                continue
            text = str(turn.get("body") or "").strip()
            # The app adds this display-only suffix while saving an attachment.
            text = re.sub(r"\n\[attached: [^\]]*\]\s*$", "", text).strip()
            if text:
                out.append({"source": "chatter", "text": text,
                            "ts": stamp(turn.get("ts")), "session": sid,
                            "title": title})
    return out


def parse_bound(value, end=False):
    if not value:
        return 0
    text = str(value).strip()
    try:
        if len(text) == 10:
            d = dt.date.fromisoformat(text)
            when = dt.datetime.combine(d, dt.time.max if end else dt.time.min,
                                       tzinfo=dt.timezone.utc)
            return int(when.timestamp())
        return stamp(text)
    except ValueError:
        return 0


def select(req, claude_root, sessions_root):
    source = str(req.get("source") or "all").lower()
    if source not in ("all", "claude", "chatter"):
        raise ValueError("source must be all, claude, or chatter")
    rows = []
    if source in ("all", "claude"):
        rows.extend(claude_prompts(claude_root))
    if source in ("all", "chatter"):
        rows.extend(chatter_prompts(sessions_root))
    since, until = parse_bound(req.get("since")), parse_bound(req.get("until"), True)
    if req.get("since") and not since:
        raise ValueError("since must be YYYY-MM-DD or an ISO timestamp")
    if req.get("until") and not until:
        raise ValueError("until must be YYYY-MM-DD or an ISO timestamp")
    rows = [r for r in rows if (not since or r["ts"] >= since)
            and (not until or not r["ts"] or r["ts"] <= until)]
    return sorted(rows, key=lambda r: r["ts"], reverse=True)


def excerpt(text, query):
    low, needle = text.lower(), query.lower()
    pos = low.find(needle)
    if pos < 0:
        return text[:EXCERPT]
    start = max(0, pos - 180)
    end = min(len(text), pos + len(query) + 600)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def search(rows, req):
    query = str(req.get("query") or "").strip()
    if not query:
        raise ValueError("search needs a non-empty query")
    limit = max(1, min(int(req.get("limit") or 12), MAX_LIMIT))
    matches = [r for r in rows if query.casefold() in r["text"].casefold()]
    result = []
    for row in matches[:limit]:
        item = {"source": row["source"], "when": iso(row["ts"]),
                "excerpt": excerpt(row["text"], query)}
        if row["source"] == "chatter":
            item.update(session=row.get("session", ""), title=row.get("title", ""))
        result.append(item)
    return {"op": "search", "query": query, "matched": len(matches),
            "returned": len(result), "matches": result}


def percentile(values, p):
    return values[min(len(values) - 1, int(len(values) * p / 100))]


def stats(rows):
    if not rows:
        return {"op": "stats", "prompts": 0, "sources": {}, "message": "no prompts matched"}
    lengths = sorted(len(r["text"]) for r in rows)
    counts = collections.Counter(r["source"] for r in rows)
    terms = collections.Counter()
    for row in rows:
        terms.update(w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", row["text"])
                     if w.lower() not in STOP_WORDS)
    dated = [r["ts"] for r in rows if r["ts"]]
    return {
        "op": "stats", "prompts": len(rows), "sources": dict(sorted(counts.items())),
        "date_range": {"first": iso(min(dated)) if dated else "",
                       "last": iso(max(dated)) if dated else ""},
        "characters": {"total": sum(lengths), "min": lengths[0],
                       "p10": percentile(lengths, 10), "median": percentile(lengths, 50),
                       "p90": percentile(lengths, 90), "max": lengths[-1],
                       "mean": round(sum(lengths) / len(lengths), 1)},
        "shape": {"single_line": sum("\n" not in r["text"] for r in rows),
                  "all_lowercase": sum(r["text"] == r["text"].lower() for r in rows),
                  "ends_question": sum(r["text"].rstrip().endswith("?") for r in rows)},
        "common_terms": [{"term": term, "prompts": count}
                         for term, count in terms.most_common(20)],
    }


def main():
    if len(sys.argv) != 3:
        print(json.dumps({"error": "usage: prompt-history.py <claude-root> <sessions-root>"}))
        return
    try:
        req = json.loads(sys.stdin.read() or "{}")
        if not isinstance(req, dict):
            raise ValueError("request must be a JSON object")
        rows = select(req, sys.argv[1], sys.argv[2])
        op = str(req.get("op") or "stats").lower()
        result = search(rows, req) if op == "search" else stats(rows) if op == "stats" else None
        if result is None:
            raise ValueError("op must be search or stats")
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, TypeError) as error:
        print(json.dumps({"error": str(error)}))


if __name__ == "__main__":
    main()
