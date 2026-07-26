"""Artist/title normalisation and fuzzy comparison for this music library.

Extracted from player/lyrics.py so tools that have no business importing
mutagen can share it. Pure stdlib and side-effect-free at import: the LRCLIB
lookup, the Spotify diff and anything else that has to decide "are these two
tag strings the same song?" must use THIS, not a second private copy that
drifts from it.

The decoration stripping is not cosmetic. Applying it lifted the LRCLIB hit
rate on this library from 42% to 60% - '(Monopoly mix)' / '(ft. X)' /
'prod. Y' suffixes are the single biggest reason a real match is missed.
"""
import re
import unicodedata

# Parenthetical/bracketed decorations that are not part of the song's name.
_DECO = re.compile(
    r"\s*[\(\[][^)\]]*\b(?:mix|remix|edit|version|ver|instrumental|inst|feat|ft|"
    r"with|prod|bonus|demo|live|remaster(?:ed)?|reprise|interlude|acoustic|"
    r"extended|radio|album|single|original|deluxe|cover|vip|bootleg|rework|"
    r"flip|dub|mono|stereo)\b[^)\]]*[\)\]]", re.IGNORECASE)
_TRAILING_PAREN = re.compile(r"\s*[\(\[][^)\]]{0,40}[\)\]]\s*$")
_DASH_FEAT = re.compile(r"\s*[-–—]\s*(?:feat\.?|ft\.?|with|prod\.?(?:\sby)?)\s.*$",
                        re.IGNORECASE)
_ARTIST_SPLIT = re.compile(r"\s*(?:&|,|;|\+|/|×|x|feat\.?|ft\.?|vs\.?|with)\s+",
                           re.IGNORECASE)
_ARTIST_PROD = re.compile(r",?\s*(?:prod\.?(?:\sby)?)\s.*$", re.IGNORECASE)


def title_variants(title):
    """Progressively less decorated forms of a track title, most specific
    first. '(Monopoly mix)' / '(ft. X)' suffixes are the single biggest reason
    a real LRCLIB entry is missed for this library."""
    out = []

    def add(s):
        s = (s or "").strip(" -–—·").strip()
        if s and s not in out:
            out.append(s)
    add(title)
    add(_DASH_FEAT.sub("", title))
    add(_DECO.sub("", title))
    add(_DECO.sub("", _DASH_FEAT.sub("", title)))
    add(_TRAILING_PAREN.sub("", _DASH_FEAT.sub("", title)))
    return out


def artist_variants(artist):
    """Full tag first, then the primary artist alone: LRCLIB indexes on a
    primary-artist name, so 'A & B' / 'A feat. B' rarely matches as written."""
    out = []

    def add(s):
        s = (s or "").strip(" -–—,&").strip()
        if s and s not in out:
            out.append(s)
    add(artist)
    add(_ARTIST_PROD.sub("", artist or ""))
    add(_ARTIST_SPLIT.split(_ARTIST_PROD.sub("", artist or ""), maxsplit=1)[0])
    return out


def fold(s):
    """Aggressive comparison key: caseless, unaccented, punctuation-free."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def title_matches(want, got):
    a, b = fold(want), fold(got)
    if not a or not b:
        return False
    if a == b:
        return True
    # A decorated tag title may legitimately contain the canonical one
    # ("Melt! (Monopoly mix)" vs "Melt!") — but only that direction, and only
    # when the canonical side is substantial enough not to match by accident.
    return (a.startswith(b) or b.startswith(a)) and min(len(a), len(b)) >= 4


def artist_matches(want, got):
    a, b = fold(want), fold(got)
    if not a or not b:
        return False
    if a == b or a.startswith(b) or b.startswith(a):
        return True
    # "A & B" vs "A": accept when one side's primary token set is contained.
    at, bt = set(a.split()), set(b.split())
    return bool(at) and bool(bt) and (at <= bt or bt <= at)


def keys(artist, title):
    """Every (artist, title) folded key a track could reasonably be known by -
    decorated and undecorated, full artist and primary artist. Intersecting
    two tracks' key sets is a cheap stand-in for the pairwise *_matches
    functions when one side is a whole library."""
    out = set()
    for a in artist_variants(artist or ""):
        fa = fold(a)
        if not fa:
            continue
        for t in title_variants(title or ""):
            ft = fold(t)
            if ft:
                out.add((fa, ft))
    return out
