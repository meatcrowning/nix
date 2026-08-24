"""The Danbooru tag vocabulary, so a prompt is looked up rather than invented.

Anima was captioned with Danbooru's tags, and a tag the site does not have does
nothing at all — it is not a weaker version of the tag you meant, it is noise
the model has never seen. A model writing an Anima prompt from memory produces
plausible-looking tags at a steady rate (`smiling_softly`, `cute_face`), and
none of them fire. So the vocabulary ships here and is SEARCHED [his,
2026-08-24].

`data/danbooru-tags.csv.gz` is the site's tag list — name, category, post
count, aliases — cut to everything with **50 posts or more** (91,357 of
140,782; below that a tag is too rare to have taught the model anything) and
sorted by count, so the first match for a prefix is also the most used one.
1 MB compressed, read lazily and once per process.

Categories are Danbooru's own: 0 general, 1 artist, 3 copyright (the series),
4 character, 5 meta. They matter to a prompt — an artist is written `@name`,
and a character wants its series beside it — so every answer carries one.

Aliases are half the value: `1girls`, `sole_female` and `female_solo` all
resolve to `1girl`, which is how a tag the model half-remembers becomes the tag
the model was trained on.

Underscores are the STORAGE spelling (that is how the site writes them) and
spaces are the PROMPT spelling; `graph.danbooru_prompt` does that conversion at
generation time, so lookups here accept either and answer in the site's form.
"""

from __future__ import annotations

import csv
import gzip
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "danbooru-tags.csv.gz")

CATEGORIES = {0: "general", 1: "artist", 3: "copyright", 4: "character",
              5: "meta"}

_ROWS = None            # [(name, category, count, [aliases])], count-descending
_BY_NAME = None         # name or alias -> index into _ROWS


def _norm(s):
    return str(s or "").strip().lower().replace(" ", "_").strip("_")


def _load():
    global _ROWS, _BY_NAME
    if _ROWS is not None:
        return _ROWS, _BY_NAME
    rows, by_name = [], {}
    try:
        with gzip.open(DATA, "rt", encoding="utf-8", newline="") as fh:
            for r in csv.reader(fh):
                if len(r) < 3 or not r[2].isdigit():
                    continue
                aliases = [a for a in (r[3].split(",") if len(r) > 3 and r[3]
                                       else []) if a]
                i = len(rows)
                rows.append((r[0], int(r[1]) if r[1].isdigit() else 0,
                             int(r[2]), aliases))
                by_name.setdefault(r[0], i)
                for a in aliases:
                    by_name.setdefault(a, i)
    except (OSError, ValueError):
        rows, by_name = [], {}      # no vocabulary is no lookups, never a crash
    _ROWS, _BY_NAME = rows, by_name
    return _ROWS, _BY_NAME


def _entry(i, rows):
    name, cat, count, aliases = rows[i]
    return {"tag": name, "category": CATEGORIES.get(cat, str(cat)),
            "posts": count, "aliases": aliases[:6]}


def resolve(tag):
    """One tag, canonical — following an alias — or None if it is not one."""
    rows, by_name = _load()
    i = by_name.get(_norm(tag))
    return _entry(i, rows) if i is not None else None


def search(query, category="", limit=25):
    """Tags matching `query`, most-used first.

    Substring, not fuzzy: an exact name (or alias) is put first, then anything
    the query is a prefix of, then anything containing it — which is the order
    a person guessing at a tag actually wants.
    """
    rows, by_name = _load()
    q = _norm(query)
    if not q or not rows:
        return []
    want = ""
    for num, label in CATEGORIES.items():
        if str(category).strip().lower() in (label, str(num)):
            want = label
            break
    exact, prefix, inside = [], [], []
    seen = set()
    hit = by_name.get(q)
    if hit is not None:
        exact.append(hit)
        seen.add(hit)
    for i, (name, cat, _count, aliases) in enumerate(rows):
        if i in seen:
            continue
        if want and CATEGORIES.get(cat, "") != want:
            continue
        if name.startswith(q) or any(a.startswith(q) for a in aliases):
            prefix.append(i)
        elif q in name or any(q in a for a in aliases):
            inside.append(i)
        if len(prefix) >= limit * 3:
            break
    out = [_entry(i, rows) for i in (exact + prefix + inside)[:max(1, int(limit))]]
    return out


def check(prompt):
    """Split a written prompt and say which tags the site does not have.

    Only the comma-separated pieces that LOOK like tags are judged — a natural
    language clause is part of how Anima is prompted and is not a misspelling,
    so anything with more than four words, or ending in a full stop, is left
    alone. Weights and `@artist` marks are stripped before the lookup.
    """
    known, unknown, renamed = [], [], []
    for raw in str(prompt or "").split(","):
        piece = raw.strip()
        if not piece:
            continue
        body = piece
        if body.endswith(")"):
            body = body.rstrip(")")
        body = body.lstrip("(").strip()
        if ":" in body:
            head, _, tail = body.rpartition(":")
            try:
                float(tail)
                body = head.strip()
            except ValueError:
                pass
        at = body.startswith("@")
        body = body.lstrip("@").strip()
        if not body:
            continue
        if body.endswith(".") or len(body.split()) > 4:
            continue                      # prose, not a tag
        got = resolve(body)
        if got is None:
            unknown.append(piece)
        elif got["tag"] != _norm(body):
            renamed.append({"wrote": piece, "tag": got["tag"],
                            "category": got["category"]})
        else:
            known.append(got["tag"] if not at else "@" + got["tag"])
    return {"known": known, "renamed": renamed, "unknown": unknown}
