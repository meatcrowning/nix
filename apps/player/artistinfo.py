"""Pure MusicBrainz artist identity and facts.

The release is the part that fails. A bootleg, a rip, a private edition or a
MusicBrainz outage leaves the album unidentified while the person who made it
is perfectly well known, so the artist resolves on its own path: from tagged
artist IDs when they exist, from the name alone when they do not. Like its
release sibling this module has no database, Qt or network dependency — the
coordinator supplies ``fetch_json`` with its cache, rate limit and threading.
"""

from __future__ import annotations

from urllib.parse import quote

# One MusicBrainz normalisation for the whole pane, not two: these are the
# release module's own text, folding and link helpers.
from releaseinfo import (WS_ROOT, _entity_url, _lucene_phrase, _number, _same,
                         _text, _url_links)

ARTIST_INC = "url-rels"
#: A name search is a guess until the name comes back exactly. Below this the
#: server itself is unsure, and a biography filed under the wrong person is
#: worse than no biography.
MIN_SEARCH_SCORE = 90


def _facts(artist):
    span = artist.get("life-span") or {}
    area = artist.get("area") or {}
    begin_area = artist.get("begin-area") or {}
    out = {
        "id": _text(artist.get("id")), "name": _text(artist.get("name")),
        "sortName": _text(artist.get("sort-name")),
        "disambiguation": _text(artist.get("disambiguation")),
        "type": _text(artist.get("type")),
        "area": _text(area.get("name")) or _text(artist.get("country")),
        "beginArea": _text(begin_area.get("name")),
        "begin": _text(span.get("begin")), "end": _text(span.get("end")),
        "ended": bool(span.get("ended")),
        "url": _entity_url("artist", artist.get("id")),
        "links": _url_links(artist), "sources": ["musicbrainz"],
        "description": "", "descriptionSource": "", "descriptionUrl": "",
    }
    out["years"] = life_span(out)
    return out


def life_span(artist):
    """`1936-`, `1936-2016`, or an empty string. Years only — a formation month
    is noise beside a name — and an ASCII dash, which the pixel font has."""
    begin, end = _text(artist.get("begin"))[:4], _text(artist.get("end"))[:4]
    if not begin and not end:
        return ""
    if begin and end:
        return begin + "-" + end
    if end:
        return "-" + end
    return begin if artist.get("ended") else begin + "-"


class ArtistInfo:
    """Resolve one artist's MusicBrainz entity without side effects."""

    def __init__(self, fetch_json):
        self.fetch_json = fetch_json

    def detail(self, artist_id):
        data = self.fetch_json(
            f"{WS_ROOT}/artist/{quote(_text(artist_id), safe='')}?fmt=json&inc={ARTIST_INC}")
        return data if isinstance(data, dict) and data.get("id") else {}

    def search(self, name):
        query = "artist:" + _lucene_phrase(name)
        found = self.fetch_json(
            f"{WS_ROOT}/artist/?fmt=json&limit=5&query={quote(query, safe='')}") or {}
        items = [item for item in found.get("artists", [])
                 if isinstance(item, dict) and item.get("id")]
        for item in sorted(items, key=lambda item: _number(item.get("score")), reverse=True):
            if _number(item.get("score")) < MIN_SEARCH_SCORE:
                break
            names = [item.get("name"), item.get("sort-name")]
            names += [alias.get("name") for alias in item.get("aliases") or []
                      if isinstance(alias, dict)]
            if any(_same(name, candidate) for candidate in names):
                return _text(item.get("id"))
        return ""

    def resolve(self, name, artist_ids=()):
        """Facts for `name`, or an empty mapping when nobody answers to it."""
        name = _text(name)
        errors = []
        for artist_id in dict.fromkeys(_text(value) for value in artist_ids or () if _text(value)):
            try:
                artist = self.detail(artist_id)
            except Exception as error:
                # A tagged ID that 404s or times out must not hide the name
                # search that would have found the same person anyway.
                errors.append(error)
                continue
            if artist:
                return _facts(artist)
        if not name:
            if errors:
                raise errors[0]
            return {}
        found = self.search(name)
        if not found:
            if errors:
                raise errors[0]
            return {}
        artist = self.detail(found)
        return _facts(artist) if artist else {}
