"""Artist identity groups: one person, many names.

Daniel Lopatin releases as Oneohtrix Point Never, as Chuck Person, as Games and
as himself, and every one of those tags is CORRECT — so the fix is not to
rewrite them into one credit. It is to let the library know the names belong to
the same person, and then answer a search for any one of them with all of the
work. The records stay filed under the name they were released as; only
MATCHING widens.

A group is a plain list of names, the first being the one it is displayed
under. Membership is folded-equality (`trackmatch.fold`) against the names he
wrote down — deliberately not `artist_matches`, whose token-subset test would
quietly enrol "Air France" into a group containing "Air". A name belongs to at
most one person: adopting it into a group removes it from any other.

The store is one portable row in infostore's user table, so a rescan cannot
lose it and `tools/dbsync.py` already carries it between top and book.
"""
import sys
from pathlib import Path

try:
    import trackmatch
except ImportError:  # running this file straight out of player/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))
    import trackmatch

import infostore

SCOPE = "artists"
KIND = "aliases"

# Seeded once, then his: the row is written the first time he edits anything,
# and after that this list is never consulted again — so removing a name here
# stays removed instead of coming back at the next launch.
DEFAULT_GROUPS = [
    ["Oneohtrix Point Never", "Daniel Lopatin", "Chuck Person", "Dania Shapes",
     "KGB Man", "Sunsetcorp", "Ford & Lopatin", "Games"],
]


#: Below this many characters, a half-typed query is not treated as a name:
#: two letters prefix half the library and would widen a search nobody aimed.
MIN_PARTIAL = 3


def _typed_towards(words, name_words):
    """Is `words` the beginning of a run of `name_words`? Each typed word must
    prefix the name word at the same place, so "point never" and "lopatin" both
    reach their name and "never point" reaches nothing."""
    if not words or len(words) > len(name_words):
        return False
    return any(all(name_words[i + j].startswith(w) for j, w in enumerate(words))
               for i in range(len(name_words) - len(words) + 1))


def _clean(names):
    """Trimmed, de-duplicated, order preserved. Folded comparison, so the same
    name typed with different case or punctuation is not added twice."""
    out, seen = [], set()
    for n in names or []:
        n = " ".join(str(n or "").split())
        key = trackmatch.fold(n)
        if key and key not in seen:
            seen.add(key)
            out.append(n)
    return out


class Aliases:
    """The groups, plus the folded name -> group index the callers use."""

    def __init__(self, groups=None):
        self.set_groups(groups or [])

    def set_groups(self, groups):
        # A group of one is just an artist. Keeping it would make an empty
        # editor read as a saved identity, and it can never widen a match.
        self.groups = [g for g in (_clean(g) for g in groups or []) if len(g) > 1]
        self._by_name = {}
        for g in self.groups:
            for n in g:
                self._by_name.setdefault(trackmatch.fold(n), g)

    def group_for(self, name):
        """Every name for whoever `name` is, or [] when nobody claims it.

        A whole name is matched first. Then the HALF-TYPED one, because that is
        what a search box gets: "oneohtrix" and "lopatin" are the person as
        surely as their full credit is, and an identity that only answers to
        the complete string reads as not working at all. One group only — text
        that could be two different people widens to neither, since guessing
        which one he meant is worse than the plain search he already had."""
        folded = trackmatch.fold(name)
        exact = self._by_name.get(folded)
        if exact is not None:
            return list(exact)
        if len(folded) < MIN_PARTIAL:
            return []
        words = folded.split()
        hits = [g for g in self.groups
                if any(_typed_towards(words, trackmatch.fold(n).split())
                       for n in g)]
        return list(hits[0]) if len(hits) == 1 else []

    def others(self, name):
        """The group minus the name asked about — what a caller SHOWS."""
        key = trackmatch.fold(name)
        return [n for n in self.group_for(name) if trackmatch.fold(n) != key]

    def expand(self, name):
        """`name`, then every other name for the same person: the alternatives
        a query is ORed over. A name nobody claims expands to itself, so a
        caller needs no special case for the ordinary library."""
        name = " ".join(str(name or "").split())
        return self.group_for(name) or ([name] if name else [])

    def set_for(self, name, names):
        """Replace the group `name` belongs to with `names` (which should
        include `name` itself). Fewer than two names dissolves the group."""
        names = _clean(names)
        key = trackmatch.fold(name)
        claimed = {trackmatch.fold(n) for n in names}
        out = []
        for g in self.groups:
            folded = {trackmatch.fold(n) for n in g}
            if key in folded:
                continue            # THIS person is being replaced wholesale
            # A name belongs to one person: adopting it here takes it away
            # from whoever else had it.
            g = [n for n in g if trackmatch.fold(n) not in claimed]
            if len(g) > 1:
                out.append(g)
        if len(names) > 1:
            out.append(names)
        self.set_groups(out)
        return self.groups


def load(con):
    body = infostore.user_get(con, SCOPE, KIND)
    groups = body.get("groups") if isinstance(body, dict) else None
    return Aliases(DEFAULT_GROUPS if groups is None else groups)


def save(con, aliases):
    infostore.user_put(con, SCOPE, KIND, {"groups": aliases.groups})
