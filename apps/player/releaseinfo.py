"""Pure MusicBrainz release identity and details provider.

The coordinator supplies ``fetch_json`` (including its cache, rate limit and
threading policy).  This module deliberately has no mutagen, Qt, database, or
network dependency, which also makes every result reproducible from fixtures.
"""

from __future__ import annotations

import json
import re
import unicodedata
from urllib.parse import quote


MB_ROOT = "https://musicbrainz.org"
WS_ROOT = MB_ROOT + "/ws/2"

# A release lookup can carry every recording's artist relations in the same
# response.  Do not turn an album with 20 tracks into 20 recording requests.
RELEASE_INC = (
    "artists+artist-credits+labels+recordings+release-groups+media+url-rels+"
    "artist-rels+recording-level-rels+release-group-level-rels"
)
GROUP_INC = "artist-credits+artist-rels+url-rels"
MAX_SEARCH_DETAILS = 4


def _text(value):
    """Return the first useful text representation of a tag/API value."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return _text(value[0]) if value else ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip()
    # Mutagen ID3 frames expose text; MP4FreeForm exposes bytes.  Keep this
    # duck-typed so importing this module never imports mutagen.
    text = getattr(value, "text", None)
    if text is not None:
        return _text(text)
    return str(value).strip()


def _mapping_value(mapping, names):
    """Case-insensitive mapping lookup for Vorbis/APE and generic test tags."""
    if not mapping:
        return ""
    try:
        keys = mapping.keys()
    except (AttributeError, TypeError):
        return ""
    wanted = {str(name).casefold() for name in names}
    for key in keys:
        rendered = str(key).casefold()
        # ID3's mapping keys are ``TXXX:<description>`` while its values are
        # frame objects.  Vorbis and APE use the description directly.
        comparable = rendered[5:] if rendered.startswith("txxx:") else rendered
        if comparable in wanted:
            try:
                return _text(mapping[key])
            except (KeyError, TypeError):
                continue
    return ""


def _freeform_value(mapping, names):
    """Read MP4 iTunes freeform tags without requiring MP4's Python class."""
    if not mapping:
        return ""
    wanted = {str(name).casefold() for name in names}
    try:
        keys = mapping.keys()
    except (AttributeError, TypeError):
        return ""
    for key in keys:
        raw = str(key)
        if not raw.casefold().startswith("----:"):
            continue
        tail = raw.rsplit(":", 1)[-1].casefold()
        if tail in wanted:
            try:
                return _text(mapping[key])
            except (KeyError, TypeError):
                continue
    return ""


def _ufid_recording_id(mapping):
    """Read Picard's ID3 UFID without importing mutagen's UFID frame type."""
    try:
        keys = mapping.keys()
    except (AttributeError, TypeError):
        return ""
    for key in keys:
        rendered = str(key).casefold()
        if not rendered.startswith("ufid:") or "musicbrainz.org" not in rendered:
            continue
        try:
            frame = mapping[key]
        except (KeyError, TypeError):
            continue
        # A real mutagen UFID stores the opaque identifier in ``data``.
        # Fixtures and older tag readers commonly expose the bytes directly.
        value = _text(getattr(frame, "data", frame))
        if value:
            return value
    return ""


def read_identity(audio):
    """Extract MusicBrainz IDs from a mutagen-like audio object.

    Picard writes these as ID3 TXXX frames, Vorbis/APE comments, or MP4 iTunes
    freeforms.  Some callers hand the tag mapping itself, which is useful for
    lazy scanner tests.  Unknown tag classes simply return the stable empty
    shape rather than coupling the scan to a particular mutagen version.
    """
    tags = getattr(audio, "tags", audio)
    out = {"releaseId": "", "releaseGroupId": "", "recordingId": "",
           "releaseTrackId": "", "artistIds": []}
    if tags is None:
        return out
    names = {
        "releaseId": ("musicbrainz_albumid", "musicbrainz album id",
                      "musicbrainz_releaseid", "musicbrainz release id"),
        "releaseGroupId": ("musicbrainz_releasegroupid", "musicbrainz release group id"),
        "recordingId": ("musicbrainz_trackid", "musicbrainz track id",
                        "musicbrainz_recordingid", "musicbrainz recording id"),
        "releaseTrackId": ("musicbrainz_releasetrackid", "musicbrainz release track id"),
        # Track/recording artist IDs and album-artist IDs have different
        # semantics.  Combining them makes every Various Artists compilation
        # look like one artist to related-music ranking.
        "artistIds": ("musicbrainz_artistid", "musicbrainz artist id"),
    }
    for field, aliases in names.items():
        value = _mapping_value(tags, aliases) or _freeform_value(tags, aliases)
        if field == "artistIds":
            # Multi-valued Vorbis values and Picard's semicolon form are both
            # seen in real libraries.  Preserve source order and remove dupes.
            values = []
            try:
                for key in tags.keys():
                    rendered = str(key).casefold()
                    comparable = rendered[5:] if rendered.startswith("txxx:") else rendered
                    if rendered.startswith("----:"):
                        comparable = rendered.rsplit(":", 1)[-1]
                    if comparable in {x.casefold() for x in aliases}:
                        raw = tags[key]
                        raw = getattr(raw, "text", raw)
                        values.extend(raw if isinstance(raw, (list, tuple)) else [raw])
            except (AttributeError, TypeError, KeyError):
                pass
            if not values and value:
                values = re.split(r"\s*;\s*", value)
            for item in values:
                # Picard's ID3 TXXX commonly carries a single semicolon-
                # separated string, while Vorbis normally exposes a list.
                for artist_id in re.split(r"\s*;\s*", _text(item)):
                    if artist_id and artist_id not in out[field]:
                        out[field].append(artist_id)
        elif value:
            out[field] = value
    # MusicBrainz also writes the recording identifier as ID3's official
    # unique-file identifier.  Prefer an explicit TXXX field when both exist.
    if not out["recordingId"]:
        out["recordingId"] = _ufid_recording_id(tags)
    album_artist_aliases = ("musicbrainz_albumartistid", "musicbrainz album artist id")
    album_artist_ids = []
    try:
        for key in tags.keys():
            rendered = str(key).casefold()
            comparable = rendered[5:] if rendered.startswith("txxx:") else rendered
            if rendered.startswith("----:"):
                comparable = rendered.rsplit(":", 1)[-1]
            if comparable not in {x.casefold() for x in album_artist_aliases}:
                continue
            raw = tags[key]
            raw = getattr(raw, "text", raw)
            values = raw if isinstance(raw, (list, tuple)) else [raw]
            for item in values:
                for artist_id in re.split(r"\s*;\s*", _text(item)):
                    if artist_id and artist_id not in album_artist_ids:
                        album_artist_ids.append(artist_id)
    except (AttributeError, TypeError, KeyError):
        pass
    if album_artist_ids:
        out["albumArtistIds"] = album_artist_ids
    return out


def _row(row, key, default=""):
    try:
        value = row[key]
    except (KeyError, TypeError, IndexError):
        value = getattr(row, key, default)
    return default if value is None else value


def _identity(row):
    raw = _row(row, "identity_json", "")
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def _fold(value):
    value = unicodedata.normalize("NFKD", _text(value)).casefold()
    return "".join(c for c in value if not unicodedata.combining(c) and c.isalnum())


def _same(left, right):
    return bool(_fold(left) and _fold(left) == _fold(right))


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _credit_name(credits):
    bits = []
    for credit in credits or []:
        if not isinstance(credit, dict):
            continue
        name = _text(credit.get("name")) or _text((credit.get("artist") or {}).get("name"))
        if name:
            bits.append(name + _text(credit.get("joinphrase")))
    return "".join(bits)


def _artist_credit_items(credits, role, scope, track_title="", track_position=0, disc=0):
    out = []
    for credit in credits or []:
        if not isinstance(credit, dict):
            continue
        artist = credit.get("artist") or {}
        artist_id = _text(artist.get("id"))
        name = _text(credit.get("name")) or _text(artist.get("name"))
        if name:
            item = {"id": artist_id, "name": name, "role": role,
                    "scope": scope, "trackTitle": track_title,
                    "trackPosition": track_position,
                    "url": _entity_url("artist", artist_id)}
            if scope == "track":
                item["disc"] = disc
            out.append(item)
    return out


def _entity_url(kind, entity_id):
    return f"{MB_ROOT}/{kind}/{quote(_text(entity_id), safe='')}" if entity_id else ""


def _relation_credits(relations, scope, track_title="", track_position=0, disc=0):
    out = []
    for relation in relations or []:
        if not isinstance(relation, dict):
            continue
        artist = relation.get("artist") or {}
        artist_id = _text(artist.get("id"))
        name = _text(relation.get("target-credit")) or _text(artist.get("name"))
        role = _text(relation.get("type"))
        attributes = relation.get("attributes") or []
        if isinstance(attributes, str):
            attributes = [attributes]
        # The MusicBrainz instrument relationship is commonly type
        # ``instrument`` with concrete instruments in attributes.  Retain
        # both pieces so the UI is truthful and relatedmusic can classify the
        # explicitly supplied performer role without guessing from names.
        values = relation.get("attribute-values") or {}
        if isinstance(values, dict):
            attributes = list(attributes) + list(values.keys()) + list(values.values())
        attributes = [_text(value) for value in attributes if _text(value)]
        if attributes:
            role = " ".join([role, *attributes]).strip()
        if name and role:
            item = {"id": artist_id, "name": name, "role": role,
                    "scope": scope, "trackTitle": track_title,
                    "trackPosition": track_position,
                    "url": _entity_url("artist", artist_id)}
            if scope == "track":
                item["disc"] = disc
            out.append(item)
    return out


def _dedupe_credits(credits):
    seen, result = set(), []
    for credit in credits:
        key = (credit.get("id"), credit.get("name"), credit.get("role"),
               credit.get("scope"), credit.get("disc"), credit.get("trackPosition"))
        if key not in seen:
            seen.add(key)
            result.append(credit)
    return result


def _url_links(*entities):
    links, seen = [], set()
    for entity in entities:
        for relation in (entity or {}).get("relations") or []:
            if not isinstance(relation, dict):
                continue
            url = _text((relation.get("url") or {}).get("resource"))
            kind = _text(relation.get("type"))
            if url.startswith(("https://", "http://")) and (kind, url) not in seen:
                seen.add((kind, url))
                links.append({"type": kind, "url": url})
    return links


def _release_tracks(release):
    tracks, media = [], []
    for index, medium in enumerate(release.get("media") or [], 1):
        if not isinstance(medium, dict):
            continue
        disc = _int(medium.get("position"), index)
        raw_tracks = medium.get("tracks") or []
        media.append({"position": disc, "format": _text(medium.get("format")),
                      "title": _text(medium.get("title")),
                      "trackCount": _int(medium.get("track-count"), len(raw_tracks))})
        for track_index, track in enumerate(raw_tracks, 1):
            if not isinstance(track, dict):
                continue
            recording = track.get("recording") or {}
            position = _int(track.get("position"), track_index)
            tracks.append({"disc": disc, "position": position,
                           "title": _text(track.get("title")) or _text(recording.get("title")),
                           "duration": _number(track.get("length"), _number(recording.get("length"))) / 1000.0,
                           "recordingId": _text(recording.get("id")),
                           "_recording": recording, "_track": track})
    return media, tracks


def _base_album(row, identity):
    artist = _text(_row(row, "album_artist")) or _text(_row(row, "artist"))
    return {
        "title": _text(_row(row, "album")), "artist": artist,
        "musicbrainzReleaseId": _text(identity.get("releaseId")),
        "musicbrainzReleaseGroupId": _text(identity.get("releaseGroupId")),
        "firstReleaseDate": "", "releaseDate": "", "country": "", "status": "",
        "barcode": "", "labels": [], "media": [], "credits": [], "tracks": [],
        "sources": [], "url": "", "links": [], "artistIds": [], "error": "",
    }


def _album_from_release(release, group, row, identity):
    album = _base_album(row, identity)
    rg = release.get("release-group") or {}
    release_credits = release.get("artist-credit") or []
    group_credits = (group or {}).get("artist-credit") or rg.get("artist-credit") or []
    album.update({
        "title": _text(release.get("title")) or album["title"],
        "artist": _credit_name(release_credits) or _credit_name(group_credits) or album["artist"],
        "musicbrainzReleaseId": _text(release.get("id")) or album["musicbrainzReleaseId"],
        "musicbrainzReleaseGroupId": _text(rg.get("id")) or _text((group or {}).get("id")) or album["musicbrainzReleaseGroupId"],
        "firstReleaseDate": _text((group or {}).get("first-release-date")) or _text(rg.get("first-release-date")),
        "releaseDate": _text(release.get("date")), "country": _text(release.get("country")),
        "status": _text(release.get("status")), "barcode": _text(release.get("barcode")),
        "url": _entity_url("release", release.get("id")), "sources": ["musicbrainz"],
    })
    labels = []
    for entry in release.get("label-info") or []:
        if not isinstance(entry, dict):
            continue
        label = entry.get("label") or {}
        label_id, name = _text(label.get("id")), _text(label.get("name"))
        if name or label_id:
            labels.append({"id": label_id, "name": name,
                           "catalogNumber": _text(entry.get("catalog-number")),
                           "url": _entity_url("label", label_id)})
    album["labels"] = labels
    media, raw_tracks = _release_tracks(release)
    album["media"] = media
    album["tracks"] = [{key: value for key, value in track.items() if not key.startswith("_")}
                       for track in raw_tracks]
    credits = _artist_credit_items(release_credits, "artist", "album")
    credits += _artist_credit_items(group_credits, "artist", "album")
    credits += _relation_credits(release.get("relations"), "album")
    credits += _relation_credits(rg.get("relations"), "album")
    credits += _relation_credits((group or {}).get("relations"), "album")
    for raw in raw_tracks:
        rec, track = raw["_recording"], raw["_track"]
        title, position, disc = raw["title"], raw["position"], raw["disc"]
        credits += _artist_credit_items(track.get("artist-credit"), "artist", "track", title, position, disc)
        credits += _artist_credit_items(rec.get("artist-credit"), "artist", "track", title, position, disc)
        credits += _relation_credits(rec.get("relations"), "track", title, position, disc)
    album["credits"] = _dedupe_credits(credits)
    # This is deliberately the release artist credit, not every player,
    # producer, or guest from the detailed credits list.  The coordinator can
    # use it for artist-level enrichment without fanning out over track roles.
    album["artistIds"] = list(dict.fromkeys(
        _text((credit.get("artist") or {}).get("id"))
        for credit in (release_credits or group_credits) if isinstance(credit, dict)
        and _text((credit.get("artist") or {}).get("id"))))
    album["links"] = _url_links(release, rg, group)
    return album


def _candidate(release, score=0.0, reason=""):
    media, tracks = _release_tracks(release)
    credits = release.get("artist-credit") or (release.get("release-group") or {}).get("artist-credit") or []
    return {
        "id": _text(release.get("id")),
        "label": " · ".join(x for x in (_text(release.get("title")), _credit_name(credits)) if x),
        "title": _text(release.get("title")), "artist": _credit_name(credits),
        "date": _text(release.get("date")), "country": _text(release.get("country")),
        "format": ", ".join(x.get("format", "") for x in media if x.get("format")),
        "discs": len(media), "trackCount": len(tracks) or sum(x.get("trackCount", 0) for x in media),
        "confidence": round(max(0.0, min(1.0, score)), 3), "reason": reason,
    }


def _local_tracks(row, album_tracks):
    # The current row can be absent from the aggregate while an album model is
    # rebuilding.  It is still valid corroborating evidence, once only.
    values = list(album_tracks or [])
    row_id = _row(row, "id", None)
    if not any(_row(item, "id", None) == row_id for item in values):
        values.append(row)
    return values


def _score_release(release, row, album_tracks):
    """Score only positive evidence; a sparse owned collection is not a CDDB."""
    score, reasons = 0.0, []
    album = _text(_row(row, "album"))
    artist = _text(_row(row, "album_artist")) or _text(_row(row, "artist"))
    credits = release.get("artist-credit") or (release.get("release-group") or {}).get("artist-credit") or []
    if _same(album, release.get("title")):
        score += .42; reasons.append("album title")
    if _same(artist, _credit_name(credits)):
        score += .24; reasons.append("album artist")
    elif artist and _fold(artist) in _fold(_credit_name(credits)):
        score += .14; reasons.append("album artist")
    media, remote_tracks = _release_tracks(release)
    remote_by_recording = {track["recordingId"] for track in remote_tracks if track["recordingId"]}
    remote_titles = {_fold(track["title"]) for track in remote_tracks if _fold(track["title"])}
    hits, duration_hits = 0, 0
    for local in _local_tracks(row, album_tracks):
        identity = _identity(local)
        rid = _text(identity.get("recordingId"))
        title = _text(_row(local, "title"))
        # A tagged recording MBID is stronger than a title.  Treat a mismatch
        # as contradictory evidence rather than quietly matching a different
        # performance with the same printed song title.
        if rid:
            if rid not in remote_by_recording:
                continue
            hits += 1
        elif title and _fold(title) in remote_titles:
            hits += 1
        else:
            continue
        duration = _number(_row(local, "duration", 0))
        if duration:
            for remote in remote_tracks:
                if (rid and remote["recordingId"] == rid) or (not rid and _same(title, remote["title"])):
                    if remote["duration"] and abs(remote["duration"] - duration) <= max(3.0, duration * .03):
                        duration_hits += 1
                    break
    if hits:
        score += min(.22, .08 + .045 * hits); reasons.append(f"{hits} track" + ("s" if hits != 1 else ""))
    if duration_hits:
        score += min(.12, .04 * duration_hits); reasons.append("duration")
    # Observed high disc positions rule out candidates with fewer discs; they
    # do not establish an exact disc total for a partial library.
    local_discs = [_int(_row(track, "disc", 0)) for track in _local_tracks(row, album_tracks)]
    max_disc = max(local_discs, default=0)
    if max_disc and len(media) < max_disc:
        # A candidate cannot be an automatic fallback match if it lacks an
        # observed disc.  Retain it as an explicitly selectable candidate.
        score = min(score, .5)
        reasons.append("disc layout conflicts")
    elif max_disc:
        score += .04; reasons.append("disc layout")
    return score, ", ".join(reasons) or "search result"


def _recording_id(row, album):
    identity = _identity(row)
    if identity.get("recordingId"):
        return _text(identity["recordingId"])
    wanted_title, wanted_track = _text(_row(row, "title")), _int(_row(row, "track", 0))
    wanted_disc = _int(_row(row, "disc", 0))
    for track in album.get("tracks") or []:
        if wanted_disc and _int(track.get("disc")) != wanted_disc:
            continue
        if wanted_track and _int(track.get("position")) == wanted_track and (
                not wanted_title or _same(wanted_title, track.get("title"))):
            return _text(track.get("recordingId"))
        if _same(wanted_title, track.get("title")):
            return _text(track.get("recordingId"))
    return ""


def _lucene_phrase(value):
    # MusicBrainz's search docs require Lucene escaping *as well as* URL
    # encoding.  Unicode remains intact through quote(), including CJK names.
    value = re.sub(r'([+\-!(){}\[\]^"~*?:\\/])', r"\\\1", _text(value))
    return '"' + value + '"'


class ReleaseInfo:
    """Resolve an album's concrete MusicBrainz release without side effects."""

    def __init__(self, fetch_json):
        self.fetch_json = fetch_json

    def _release_url(self, release_id):
        return f"{WS_ROOT}/release/{quote(_text(release_id), safe='')}?fmt=json&inc={RELEASE_INC}"

    def _group(self, release):
        group_id = _text((release.get("release-group") or {}).get("id"))
        if not group_id:
            return {}, ""
        try:
            return self.fetch_json(
                f"{WS_ROOT}/release-group/{quote(group_id, safe='')}?fmt=json&inc={GROUP_INC}") or {}, ""
        except Exception as error:
            # Group prose/credits are supplementary.  A valid release remains
            # useful if its group was deleted or a transient request failed.
            return {}, str(error)

    def _detail(self, release_id):
        data = self.fetch_json(self._release_url(release_id))
        return data if isinstance(data, dict) and data.get("id") else {}

    def _result(self, status, candidates, album, row):
        return {"status": status, "candidates": candidates, "album": album,
                "recordingId": _recording_id(row, album)}

    def resolve(self, row, album_tracks, preferred_release_id=""):
        identity = _identity(row)
        baseline = _base_album(row, identity)
        release_id = _text(preferred_release_id) or _text(identity.get("releaseId"))
        if release_id:
            # This is the required identity request.  Let the coordinator
            # distinguish a temporary network failure from a genuine no-match.
            release = self._detail(release_id)
            if not release:
                return self._result("no_match", [], baseline, row)
            group, group_error = self._group(release)
            score, reason = _score_release(release, row, album_tracks)
            reason = "preferred release id" if preferred_release_id else "release id tag"
            candidate = _candidate(release, max(.95, score), reason)
            album = _album_from_release(release, group, row, identity)
            album["error"] = group_error
            return self._result("ready", [candidate], album, row)

        title = _text(_row(row, "album"))
        artist = _text(_row(row, "album_artist")) or _text(_row(row, "artist"))
        if not (title and artist):
            return self._result("no_match", [], baseline, row)
        query_parts = ["release:" + _lucene_phrase(title),
                       "artist:" + _lucene_phrase(artist)]
        group_id = _text(identity.get("releaseGroupId"))
        if group_id:
            # `rgid` is MusicBrainz's release-search field for the release
            # group's MBID.  This keeps a tagged group from falling through to
            # a same-title edition in a different group.
            query_parts.append("rgid:" + _lucene_phrase(group_id))
        query = " AND ".join(query_parts)
        url = f"{WS_ROOT}/release/?fmt=json&limit=8&query={quote(query, safe='')}"
        found = self.fetch_json(url) or {}
        releases = [item for item in found.get("releases", []) if isinstance(item, dict) and item.get("id")]
        # Search results do not contain track timings or recording IDs.  Bound
        # corroboration to the strongest few, never one request per owned song.
        preliminary = sorted(releases, key=lambda item: (
            _same(title, item.get("title")), _same(artist, _credit_name(item.get("artist-credit"))),
            _number(item.get("score"))), reverse=True)[:MAX_SEARCH_DETAILS]
        detailed = []
        detail_errors = []
        for item in preliminary:
            try:
                detail = self._detail(item.get("id"))
            except Exception as error:
                detail_errors.append(error)
                detail = {}
            detail_group = _text((detail.get("release-group") or {}).get("id")) if detail else ""
            if detail and (not group_id or not detail_group or detail_group == group_id):
                detailed.append(detail)
        scored = []
        for detail in detailed:
            score, reason = _score_release(detail, row, album_tracks)
            scored.append((_candidate(detail, score, reason), detail))
        scored.sort(key=lambda pair: pair[0]["confidence"], reverse=True)
        candidates = [candidate for candidate, _ in scored]
        if not scored:
            if detail_errors:
                raise detail_errors[0]
            return self._result("no_match", candidates, baseline, row)
        best, detail = scored[0]
        runner_up = candidates[1]["confidence"] if len(candidates) > 1 else 0.0
        # A search is an assertion only with strong evidence and separation.
        if best["confidence"] < .82 or (len(candidates) > 1 and best["confidence"] - runner_up < .12):
            return self._result("ambiguous", candidates, baseline, row)
        group, group_error = self._group(detail)
        album = _album_from_release(detail, group, row, identity)
        album["error"] = group_error
        return self._result("ready", candidates, album, row)
