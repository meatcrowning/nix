#!/usr/bin/env python3
"""Tag-axis album-split detection for the curation pipeline.

This is the axis the PLAYER groups on (album_artist + album TAGS), as opposed
to curate.py's original `groups`, which clusters on FOLDER names and so finds
almost none of what the user sees twice in the player. Every stage that needs
"which albums are really one album" (retag, merge, verify) builds on the
clusters produced here, so the definition lives in exactly one place.

A CLUSTER is a set of (album_artist, album) tag-strings whose folds collide.
Each cluster is classified into exactly one action:

  retag    every variant lives in the SAME directory -> the only difference
           is the tag string. Safe: rewrite tags to one canonical spelling,
           move nothing. (case/punct/accent-only differences)
  merge    variants span >1 directory AND their folded track title sets
           overlap -> one album split across dirs (a reissue/edition split).
           Feed to merge.py.
  board    variants span >1 directory with DISJOINT tracklists, or the fold
           only collided because CJK/symbols stripped to empty, or a variant
           word (remix/demos/live/instrumental/…) is in play -> a judgement
           call. Never auto-acted; listed for the goetia board.

Deliberately NOT here: compilation folders (album_artist Various/blank) are
never clustered — a shared compilation tag across per-artist subfolders is
the library's normal shape, not a split.
"""
import collections
import re
import unicodedata

import common as C

# Words whose presence between two variants means "different content", never
# an auto-merge: a remixes/demos/live disc is a different record, not a copy.
VARIANT_WORD = re.compile(
    r"\b(remix(?:es|ed)?|instrumentals?|sessions?|demos?|reworks?|versions|"
    r"unmixed|alternate|covers?|acoustics?|live|unplugged|outtakes?|"
    r"b[- ]sides?|bonus tracks?|lost tracks?)\b", re.IGNORECASE)

# Edition noise that CAN fold away between two variants of one album.
EDITION_WORD = re.compile(
    r"\b(deluxe|remaster(?:ed)?|expanded|edition|anniversary|reissue|"
    r"bonus|mono|stereo|explicit)\b", re.IGNORECASE)


def fold(s):
    """Aggressive fold: caseless, unaccented, punctuation/symbol-free."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^a-z0-9\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+", "", s)


_NOT_AN_ARTIST = {"", "variousartists", "various", "va", "unknownartist",
                  "unknownalbum", "unknown"}


def _is_compilation(aa_fold):
    return aa_fold in _NOT_AN_ARTIST


def clusters(rows):
    """Group rows into tag-identity clusters. Returns a list of dicts:
      {key, variants: {(aa, al): [rows]}, action, reason}
    Only clusters with >1 distinct (aa, al) variant are returned.
    """
    ident = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        al = r.get("album") or ""
        if not al:
            continue
        aa = r.get("album_artist") or r.get("artist") or ""
        key = (fold(aa), fold(al))
        if not key[1] or _is_compilation(key[0]):
            continue
        ident[key][(aa, al)].append(r)

    out = []
    for key, variants in ident.items():
        if len(variants) < 2:
            continue
        out.append({"key": key, "variants": variants,
                    **_classify(variants)})
    return out


def _classify(variants):
    """Decide retag / merge / board for one cluster's variants."""
    raws = [a + " " + al for a, al in variants]
    # fold() strips CJK/symbols; two DIFFERENT albums whose folds both
    # collapse to the same short/empty string (「ƒƒ∆」 vs ナイトライフ) are
    # not one album. Guard: if the folded key is short, require the raw
    # strings to share real content (>=0.5 similarity) to auto-act.
    folded_al = min((fold(al) for _, al in variants), key=len)
    weak_key = len(folded_al) < 6

    # variant words present on some but not all -> different content
    vw = [bool(VARIANT_WORD.search(x)) for x in raws]
    mixed_variant = any(vw) and not all(vw)

    dirsets = {tuple(sorted({f"{r['album_artist_dir']}/{r['album_dir']}"
                             for r in recs}))
               for recs in variants.values()}
    same_dir = len(dirsets) == 1

    # folded-title overlap across variants (are these the same songs?)
    tsets = [{C.fold(r.get("title") or "") for r in recs}
             for recs in variants.values()]
    overlap = set.intersection(*tsets) if tsets else set()
    smallest = min((len(t) for t in tsets), default=0)
    mostly_shared = smallest > 0 and len(overlap) >= smallest / 2

    edition_only = all(
        fold(EDITION_WORD.sub("", a + " " + al)) == fold(EDITION_WORD.sub("", raws[0]))
        for a, al in variants)

    # weak keys are only a hazard when the variants DISAGREE in content:
    # same dir + shared tracklist means the short fold ("maya", "igor",
    # "00203") is a spelling difference, not two albums colliding.
    if same_dir:
        return {"action": "retag", "reason": "same dir, tag spelling only"}
    if weak_key or mixed_variant:
        return {"action": "board",
                "reason": "weak fold key" if weak_key else "variant word differs"}
    if mostly_shared or edition_only:
        return {"action": "merge", "reason": "split across dirs, shared tracklist"}
    return {"action": "board", "reason": "disjoint tracklists across dirs"}


def load_and_cluster(scan_path=None):
    import json
    rows = json.loads((scan_path or C.SCAN_JSON).read_text()
                      if hasattr((scan_path or C.SCAN_JSON), "read_text")
                      else open(scan_path or C.SCAN_JSON).read())
    return clusters(rows)
