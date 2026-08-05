#!/usr/bin/env python3
"""Tag-axis album-split detection for the curation pipeline.

Groups the scan rows into album clusters the way the PLAYER shows them —
the player groups by exact (album, COALESCE(album_artist, artist)) tag pair
(player/main.py rebuild_albums), so ANY raw-tag difference is a duplicate
entry on screen. This module finds which of those pairs are really one
album.

Matching is FUZZY on both axes, with guards:
  - artist: trackmatch.artist_matches (handles 'A feat. B' vs 'A',
    joiners, token order) or fold equality. A MISSING album_artist falls
    back to the track artist (the player's own COALESCE rule).
  - title: exact fold, OR fuzzy ratio > 0.88, OR containment — but never
    when distinguishing numbers differ (Vol 1 vs Vol 2, UKF 2010 vs 2011),
    never when one side carries a variant suffix the other lacks
    (Renaissance vs Renaissance (Remixes)), never across sequel tails
    (In Decay vs In Decay, Too).

Actions:
  retag   same directory, tag spelling only            -> retag.py
  merge   >1 directory, shared folded track titles     -> merge.py
  board   anything else (disjoint tracklists across dirs, weak fold
          collisions)                                  -> him, never auto
"""
import collections
import difflib
import re
import unicodedata

import common as C
import trackmatch

VARIANT_WORD = re.compile(
    r"\b(remix(?:es|ed)?|instrumentals?|sessions?|demos?|reworks?|versions|"
    r"unmixed|alternate|covers?|acoustics?|live|unplugged|outtakes?|"
    r"b[- ]sides?|bonus tracks?|lost tracks?)\b", re.IGNORECASE)

EDITION_WORD = re.compile(
    r"\b(deluxe|remaster(?:ed)?|expanded|edition|anniversary|reissue|"
    r"bonus|mono|stereo|explicit)\b", re.IGNORECASE)

_NUMERAL = re.compile(r"\d+")
_ROMAN_TOKEN = re.compile(r"^(i{1,3}|iv|vi{0,3}|ix|x)$")
_SEQUEL_TAIL = re.compile(r"\btoo\s*$")


def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^a-z0-9぀-ヿ㐀-鿿가-힯]+", "", s)


_NOT_AN_ARTIST = {"", "variousartists", "various", "va", "unknownartist",
                  "unknownalbum", "unknown"}


def _is_compilation(aa_fold):
    return aa_fold in _NOT_AN_ARTIST


def _distinguishing(raw):
    """Numbers/roman numerals from the RAW title (word boundaries intact),
    so 'SAILORWAVE II' vs 'SAILORWAVE III' and 'UKF 2010' vs '2011' differ
    even though the fold glues the numeral onto the title."""
    digits = set(_NUMERAL.findall(raw or ""))
    romans = {t.casefold() for t in re.findall(r"[A-Za-z]+", (raw or "").casefold())
              if _ROMAN_TOKEN.match(t)}
    return digits, romans


def _same_title(fa, fb, raw_a="", raw_b=""):
    """fa, fb: folded album titles; raw_a/raw_b: unfolded, for numeral
    extraction. Guards from the pre-tag-axis groups: numbers and roman
    numerals must match exactly, variant-suffix presence must match,
    sequel tails block containment."""
    if not fa or not fb:
        return False
    if fa == fb:
        return True
    va, vb = bool(VARIANT_WORD.search(fa)), bool(VARIANT_WORD.search(fb))
    if va != vb:
        return False
    if _SEQUEL_TAIL.search(fa) or _SEQUEL_TAIL.search(fb):
        return False
    da, ra = _distinguishing(raw_a or fa)
    db, rb = _distinguishing(raw_b or fb)
    if da != db or ra != rb:
        return False
    if min(len(fa), len(fb)) >= 8 and (fa in fb or fb in fa):
        return True
    # 0.85 catches a single dropped word ('thatwecanplay' vs 'thatweplay' =
    # 0.87); the distinguishing-numbers / variant / sequel guards above carry
    # the weight of keeping real different releases apart, not the ratio.
    return difflib.SequenceMatcher(None, fa, fb).ratio() > 0.85


def _same_artist(aa_a, art_a, aa_b, art_b):
    """Compare two rows' artist identity, album_artist first, track artist
    as fallback (the player's COALESCE). trackmatch.artist_matches handles
    'A feat. B' vs 'A' and token order."""
    fa, fb = fold(aa_a) or fold(art_a), fold(aa_b) or fold(art_b)
    if _is_compilation(fa) or _is_compilation(fb):
        return False
    if fa == fb:
        return True
    for x in (aa_a, art_a):
        for y in (aa_b, art_b):
            if x and y and trackmatch.artist_matches(x, y):
                return True
    return False


def clusters(rows):
    """Union-find over (album_artist, album) tag identities, fuzzy on both
    axes. Returns [{key, variants: {(aa,al): [rows]}, action, reason}]."""
    ident = collections.defaultdict(list)
    for r in rows:
        al = r.get("album") or ""
        if not al:
            continue
        aa = r.get("album_artist") or ""
        ident[(aa, al)].append(r)

    keys = list(ident)
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    def titles(k):
        return {C.fold(r.get("title") or "") for r in ident[k]}

    for i in range(len(keys)):
        aa_i, al_i = keys[i]
        art_i = ident[keys[i]][0].get("artist") or ""
        fa = fold(al_i)
        for j in range(i + 1, len(keys)):
            aa_j, al_j = keys[j]
            art_j = ident[keys[j]][0].get("artist") or ""
            if not _same_artist(aa_i, art_i, aa_j, art_j):
                continue
            if not _same_title(fa, fold(al_j), al_i, al_j):
                continue
            # When the artist strings fold DIFFERENTLY (not merely one side
            # blank), a title match alone is not enough: a one-off remix
            # track tagged with the host album ('Fashion (ESPRIT 空想 Remix)'
            # under Satin Sheets' St. Francis) would fuse two artists'
            # records. Require shared folded track titles as proof — unless
            # both sides already live in the SAME directory, where the
            # album tag + dir agreement is the proof (a stray feat.-credit
            # retag of one file must not block the fold).
            fi, fj = fold(aa_i) or fold(art_i), fold(aa_j) or fold(art_j)
            if fi != fj and fi and fj:
                di = {f"{r['album_artist_dir']}/{r['album_dir']}" for r in ident[keys[i]]}
                dj = {f"{r['album_artist_dir']}/{r['album_dir']}" for r in ident[keys[j]]}
                if di != dj and not (titles(keys[i]) & titles(keys[j])):
                    continue
            union(keys[i], keys[j])

    groups = collections.defaultdict(dict)
    for k in keys:
        groups[find(k)][k] = ident[k]

    out = []
    for variants in groups.values():
        if len(variants) < 2:
            continue
        rep = next(iter(variants))
        out.append({"key": (fold(rep[0]), fold(rep[1])),
                    "variants": variants, **_classify(variants)})
    return out


def _classify(variants):
    dirsets = {tuple(sorted({f"{r['album_artist_dir']}/{r['album_dir']}"
                             for r in recs}))
               for recs in variants.values()}
    same_dir = len(dirsets) == 1
    tsets = [{C.fold(r.get("title") or "") for r in recs}
             for recs in variants.values()]
    overlap = set.intersection(*tsets) if tsets else set()
    smallest = min((len(t) for t in tsets), default=0)
    mostly_shared = smallest > 0 and len(overlap) >= smallest / 2
    # variant-word asymmetry ('Renaissance' vs 'Renaissance (Remixes)',
    # 'Anything in Return' vs '... (instrumentals)') = different content,
    # never auto-acted, however strong the artist/title match
    raws = [al for (_, al) in variants]
    vw = [bool(VARIANT_WORD.search(x)) for x in raws]
    if any(vw) and not all(vw):
        return {"action": "board", "reason": "variant word differs"}
    # every variant's artist identity folds to the same string (one side
    # may be blank and leaning on its track artist) = proven same artist
    artist_folds = set()
    for (aa, al), recs in variants.items():
        artist_folds.add(fold(aa) or fold(recs[0].get("artist") or ""))
    same_artist_proven = len(artist_folds) == 1

    if same_dir:
        # same dir + same folded artist (one side possibly blank) = pure
        # spelling. A feat./collab credit that trackmatch recognises as a
        # superset of the main artist is also a retag. Two UNRELATED artist
        # strings under one dir with no shared titles is a mistagged
        # one-off (a remix track filed under the host album) — board.
        if same_artist_proven:
            return {"action": "retag", "reason": "same dir, tag spelling only"}
        strs = [k[0] or (recs[0].get("artist") or "") for k, recs in variants.items()]
        if any(trackmatch.artist_matches(a, b)
               for a in strs for b in strs if a and b and a != b):
            return {"action": "retag", "reason": "same dir, feat/collab credit"}
        if overlap:
            return {"action": "retag", "reason": "same dir, shared tracks"}
        return {"action": "board", "reason": "same dir, different artists, no shared tracks"}
    if mostly_shared:
        return {"action": "merge", "reason": "split across dirs, shared tracklist"}
    if same_artist_proven:
        # artist proven + titles equal/contain (a dropped bracket, a lost
        # word inside a longer title) but NO shared tracks = one album split
        # with zero overlap (his Games 'That We Can Play'/'That We Play').
        # A ratio-only fuzzy match with disjoint tracklists stays board:
        # that's the shape of 'different record, similar name'.
        folds = [fold(al) for (aa, al) in variants]
        tight = all(f == folds[0] or
                    (min(len(f), len(folds[0])) >= 8 and (f in folds[0] or folds[0] in f))
                    for f in folds)
        if tight:
            return {"action": "merge", "reason": "same artist, tight title, no overlap"}
        # ratio-only match + proven same artist + BOTH sides are tiny
        # fragments (<=2 tracks): a stray-tagged remnant of the same album
        # (Games 'That We Can Play' 1t vs 'That We Play' 1t). Folding two
        # strays is reversible; leaving them is a duplicate listing.
        if all(len(recs) <= 2 for recs in variants.values()):
            return {"action": "merge", "reason": "same artist, fuzzy title, tiny fragments"}
    return {"action": "board", "reason": "disjoint tracklists across dirs"}


def load_and_cluster(scan_path=None):
    import json
    rows = json.loads((scan_path or C.SCAN_JSON).read_text()
                      if hasattr((scan_path or C.SCAN_JSON), "read_text")
                      else open(scan_path or C.SCAN_JSON).read())
    return clusters(rows)
