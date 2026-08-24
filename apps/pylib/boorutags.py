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
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "danbooru-tags.csv.gz")

CATEGORIES = {0: "general", 1: "artist", 3: "copyright", 4: "character",
              5: "meta"}

#: Anima's OWN caption vocabulary, which is not on Danbooru's tag list and must
#: not be reported as invented: the ratings, the era buckets and the `year:N`
#: form the captions use.
ANIMA_META = {"safe", "sensitive", "nsfw", "explicit", "questionable",
              "newest", "recent", "mid", "early", "old", "oldest"}

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


def _words(name):
    """A tag's words, for a whole-word match: `iwakura_lain` is two, and the
    parenthesised qualifier of `rebecca_(cyberpunk)` is one of its own."""
    return set(re.split(r"[_()\s]+", name))


def _entry(i, rows):
    name, cat, count, aliases = rows[i]
    return {"tag": name, "category": CATEGORIES.get(cat, str(cat)),
            "posts": count, "aliases": aliases[:6]}


def resolve(tag):
    """One tag, canonical — following an alias — or None if it is not one."""
    rows, by_name = _load()
    i = by_name.get(_norm(tag))
    return _entry(i, rows) if i is not None else None


#: The counting words a model reaches for instead of the tag. Danbooru's counts
#: are `1girl`/`2girls`/`1boy`, never "one girl" — and "one girl" is not an
#: alias of anything, so it resolves to nothing and does nothing in the picture.
#: This is the one class of near-miss common enough to be worth a table [his,
#: 2026-08-24, after a prompt went out with "one girl" in it].
#: `a`/`an` are deliberately NOT here: "a girl" is how a sentence starts, and
#: rewriting it to `1girl` mangles the natural-language clause Anima is also
#: prompted with.
_NUMBER_WORD = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                "six": "6"}


def canonical(tag):
    """The tag Danbooru actually has for what was written, or None.

    Beyond `resolve`'s exact-or-alias lookup it tries the near-misses that are
    mechanical: a spelled-out count (`one girl` -> `1girl`), and the same with
    the space closed up. Anything it cannot land on a real tag comes back None
    rather than a guess — a wrong tag is worse than an unknown one, because it
    fires something.
    """
    got = resolve(tag)
    if got:
        return got
    parts = _norm(tag).split("_")
    if len(parts) >= 2 and parts[0] in _NUMBER_WORD:
        digit = _NUMBER_WORD[parts[0]]
        rest = "_".join(parts[1:])
        for candidate in (digit + rest, digit + "_" + rest):
            got = resolve(candidate)
            if got:
                return got
    return None


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
    # WORD BOUNDARY BEATS PREFIX. Danbooru's names are underscore-separated, so
    # "lain" is a whole word in `iwakura_lain` and a fragment inside
    # `cu_chulainn_(fate)` — and ranking prefixes above everything buried the
    # character he actually meant under six matches he did not [his,
    # 2026-08-24: it invented Lain's appearance rather than tagging her].
    # Buckets, each count-ordered because `rows` is: exact, whole word, prefix,
    # substring.
    exact, word, prefix, inside = [], [], [], []
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
        names = [name] + aliases
        if any(q in _words(n) for n in names):
            word.append(i)
        elif any(n.startswith(q) for n in names):
            prefix.append(i)
        elif any(q in n for n in names):
            inside.append(i)
        if len(word) + len(prefix) >= limit * 4:
            break
    out = [_entry(i, rows) for i in
           (exact + word + prefix + inside)[:max(1, int(limit))]]
    return out


def check(prompt):
    """Split a written prompt and say which tags the site does not have.

    Only the comma-separated pieces that LOOK like tags are judged — a natural
    language clause is part of how Anima is prompted and is not a misspelling,
    so anything ending in a full stop, or longer than eight words, is left
    alone. Weights and `@artist` marks are stripped before the lookup.

    Three buckets out: `unknown` (short and not a tag — invented), `suspect`
    (five to eight words with no full stop, which is usually a character or a
    series written as a phrase instead of as its tag), and `renamed` (real, but
    written the way the site does not).
    """
    known, unknown, renamed, suspect = [], [], [], []
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
                # A WEIGHT, not any number: `year:2005` is a tag Anima was
                # captioned with, and treating its 2005 as a weight left it
                # looking like the invented tag `year`.
                if -4.0 <= float(tail) <= 4.0:
                    body = head.strip()
            except ValueError:
                pass
        at = body.startswith("@")
        body = body.lstrip("@").strip()
        if not body:
            continue
        if _norm(body) in ANIMA_META or re.match(r"^year[:_ ]\d{4}$", _norm(body)):
            known.append(body)
            continue
        words = len(body.split())
        if body.endswith(".") or words > 8:
            continue                      # prose, not a tag
        got = canonical(body)
        if got is None:
            # 5-8 words with no full stop, sitting in a tag run, is usually a
            # character written as a phrase — "lain from serial experiments
            # lain" instead of the tag `iwakura lain` [his, 2026-08-24]. It is
            # reported apart from the short ones because it MIGHT be a
            # deliberate clause, and the fix is different: look the character
            # up, do not delete the words.
            (suspect if words > 4 else unknown).append(piece)
        elif got["tag"] != _norm(body):
            renamed.append({"wrote": piece, "tag": got["tag"],
                            "category": got["category"]})
        else:
            known.append(got["tag"] if not at else "@" + got["tag"])
    return {"known": known, "renamed": renamed, "unknown": unknown,
            "suspect": suspect}
