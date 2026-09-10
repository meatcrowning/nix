"""Pure ranking for the player's related-music pane.

The caller owns the library query, cache, and Last.fm request.  This module
only joins those already available values; it never opens a database or makes
network requests.  In particular, a credit is useful only when its scope can
be tied to the track or release which supplied it.
"""

import json
import re
import urllib.parse

try:
    from pylib import trackmatch
except ImportError:  # useful when this file is run directly from player/
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))
    import trackmatch


# These are intentionally small.  A broad thesaurus makes a genre look like
# evidence when it is only a very weak hint ("rock" and "alternative" are not
# interchangeable here).
_GENRE_GROUPS = (
    frozenset(("ambient", "ambient music")),
    frozenset(("electronic", "electronica")),
    frozenset(("hip hop", "hip-hop", "rap")),
    frozenset(("r&b", "rnb", "rhythm and blues")),
)
_GENRE_ALIAS = {}
for _group in _GENRE_GROUPS:
    _canonical = min(_group)
    for _genre in _group:
        _GENRE_ALIAS[trackmatch.fold(_genre)] = _canonical

_ALLOWED_CREDIT_ROLES = {
    "producer": "producer",
    "remixer": "remixer",
    "composer": "composer",
    "songwriter": "composer",
    "writer": "composer",
    "performer": "performer",
    "vocalist": "performer",
    "vocals": "performer",
    "instrumentalist": "performer",
    "instrument": "performer",
    # MusicBrainz instrument relationships carry the instrument as an
    # explicit type or attribute.  This finite vocabulary recognizes those
    # supplied facts; it does not infer instruments from an artist name.
    "guitar": "performer", "bass": "performer", "drums": "performer",
    "drummer": "performer", "percussion": "performer", "piano": "performer",
    "keyboard": "performer", "synthesizer": "performer", "violin": "performer",
    "cello": "performer", "saxophone": "performer", "trumpet": "performer",
    "artist": "performer",
}
_ROLE_WORD = re.compile(r"[a-z0-9]+")
_IDENTITY_VARIANT = re.compile(
    r"\b(?:live|remix|mix|edit|version|instrumental|acoustic|demo|rework|"
    r"bootleg|dub|radio|extended|vip|mono|stereo)\b", re.IGNORECASE)


def _mapping(value):
    if isinstance(value, dict):
        return value
    try:
        return {key: value[key] for key in value.keys()}
    except (AttributeError, KeyError, TypeError):
        return {}


def _value(obj, *names, default=""):
    obj = _mapping(obj)
    for name in names:
        value = obj.get(name)
        if value is not None and value != "":
            return value
    return default


def _text(value):
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def _json_dict(value):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        value = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _identity(obj):
    """Return the optional identity JSON merged over raw row aliases."""
    row = _mapping(obj)
    cached = row.get("_related_identity")
    if isinstance(cached, dict):
        return cached
    out = {}
    raw = _json_dict(row.get("identity_json", row.get("identityJson", {})))
    nested = raw.get("identity")
    if isinstance(nested, dict):
        out.update(nested)
    out.update(raw)
    for key in (
        "recordingId", "recording_id", "musicbrainzRecordingId", "mbRecordingId",
        "releaseId", "release_id", "musicbrainzReleaseId",
        "releaseGroupId", "release_group_id", "musicbrainzReleaseGroupId",
        "releaseTrackId", "release_track_id", "musicbrainzReleaseTrackId",
        "artistId", "artist_id", "musicbrainzArtistId", "artistIds",
    ):
        if key in row and row[key] not in (None, "") and key not in out:
            out[key] = row[key]
    return out


def _first_id(obj, *names):
    value = _value(obj, *names)
    if isinstance(value, dict):
        value = _value(value, "id", "mbid")
    return _text(value)


def _ids(obj, kind):
    ident = _identity(obj)
    names = {
        "recording": ("recordingId", "recording_id", "musicbrainzRecordingId", "mbRecordingId"),
        "release": ("releaseId", "release_id", "musicbrainzReleaseId"),
        "group": ("releaseGroupId", "release_group_id", "musicbrainzReleaseGroupId"),
        "release_track": ("releaseTrackId", "release_track_id", "musicbrainzReleaseTrackId"),
    }[kind]
    for name in names:
        value = ident.get(name)
        if value not in (None, ""):
            return _text(value)
    return ""


def _artist_ids(obj):
    cached = _mapping(obj).get("_related_artist_ids")
    if isinstance(cached, frozenset):
        return cached
    ident = _identity(obj)
    values = []
    for name in ("artistIds", "artist_ids"):
        value = ident.get(name)
        if isinstance(value, (list, tuple, set)):
            values.extend(value)
        elif value:
            values.append(value)
    for name in ("artistId", "artist_id", "musicbrainzArtistId"):
        if ident.get(name):
            values.append(ident[name])
    return {_text(x) for x in values if _text(x)}


def _prepared_track(obj):
    """Shallow-copy one row and retain parsed identity for this invocation."""
    raw = _mapping(obj)
    if not raw:
        return {}
    if isinstance(raw.get("_related_identity"), dict):
        return raw
    result = dict(raw)
    ident = _identity(raw)
    result["_related_identity"] = ident
    values = []
    for name in ("artistIds", "artist_ids"):
        value = ident.get(name)
        values.extend(value if isinstance(value, (list, tuple, set)) else [value])
    for name in ("artistId", "artist_id", "musicbrainzArtistId"):
        values.append(ident.get(name))
    result["_related_artist_ids"] = frozenset(_text(value) for value in values if _text(value))
    return result


def _track_id(obj):
    value = _value(obj, "id", "trackId", "track_id", default=None)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _title(obj):
    return _text(_value(obj, "title", "name", "track"))


def _artist(obj):
    value = _value(obj, "artist", "artistName", "album_artist", "albumArtist")
    if isinstance(value, dict):
        value = _value(value, "name", "title")
    if isinstance(value, list):
        value = ", ".join(_text(x) for x in value if _text(x))
    return _text(value)


def _album(obj):
    return _text(_value(obj, "album", "albumTitle", "release", "releaseTitle"))


def _year(obj):
    value = _value(obj, "orig_year", "origYear", "year", "date", default=None)
    match = re.match(r"\s*(\d{4})", _text(value))
    return int(match.group(1)) if match else None


def _position(obj):
    value = _value(obj, "trackPosition", "track_position", "position", "tracknumber",
                    "track_number", "number", "track", default=None)
    try:
        # Tags sometimes contain "1/12".  Disc is not needed to establish a
        # safe title match, but preserving the first component is useful.
        return int(str(value).split("/", 1)[0])
    except (TypeError, ValueError):
        return None


def _disc(obj):
    value = _value(obj, "disc", "discNumber", "disc_number", default=None)
    try:
        return int(str(value).split("/", 1)[0])
    except (TypeError, ValueError):
        return None


def _fold_title(value):
    return trackmatch.fold(_text(value))


def _song_exact(a, b):
    """Conservative fallback identity; it retains live/remix distinctions."""
    return bool(_title(a) and _artist(a) and
                _fold_title(_title(a)) == _fold_title(_title(b)) and
                trackmatch.fold(_artist(a)) == trackmatch.fold(_artist(b)))


def _song_match(a, b):
    if _song_exact(a, b):
        return True
    # Last.fm commonly omits a decoration which is present in a local tag.
    # trackmatch.title_matches is directional-safe and requires four chars.
    if (_IDENTITY_VARIANT.search(_title(a)) or
            _IDENTITY_VARIANT.search(_title(b))):
        return False
    return bool(_artist(a) and _artist(b) and trackmatch.artist_matches(_artist(a), _artist(b))
                and trackmatch.title_matches(_title(a), _title(b)))


def _genre_keys(value):
    if isinstance(value, (list, tuple, set)):
        parts = value
    else:
        parts = re.split(r"[,;/|]", _text(value))
    result = set()
    for part in parts:
        folded = trackmatch.fold(part)
        if not folded:
            continue
        result.add(_GENRE_ALIAS.get(folded, folded))
    return result


def _remote_artist(item):
    value = _value(item, "artist", "artistName")
    if isinstance(value, dict):
        return _text(_value(value, "name", "title"))
    return _text(value)


def _safe_url(value):
    value = _text(value)
    parsed = urllib.parse.urlparse(value)
    return value if parsed.scheme.lower() in ("http", "https") and parsed.netloc else ""


def _lastfm_url(artist, title):
    return "https://www.last.fm/music/%s/_/%s" % (
        urllib.parse.quote(artist, safe=""), urllib.parse.quote(title, safe=""))


def _remote_url(item, artist, title):
    return _safe_url(_value(item, "url", "sourceUrl", "source_url")) or _lastfm_url(artist, title)


def _album_id(album, kind):
    names = {
        "release": ("musicbrainzReleaseId", "releaseId", "release_id"),
        "group": ("musicbrainzReleaseGroupId", "releaseGroupId", "release_group_id"),
    }[kind]
    return _first_id(album, *names)


def _album_index(albums):
    """Only a concrete release can supply edition-specific credits."""
    release = {}
    for album in albums:
        release_id = _album_id(album, "release")
        if release_id:
            release.setdefault(release_id, album)
    return release


def _album_for_track(track, index):
    # The coordinator overlays resolved directory links before ranking. A
    # group tag or matching album title alone cannot establish the edition,
    # even if only one edition happens to have been downloaded so far.
    return index.get(_ids(track, "release"), {})


def _credit_role(value):
    if isinstance(value, (list, tuple, set)):
        value = " ".join(_text(x) for x in value)
    words = _ROLE_WORD.findall(trackmatch.fold(value))
    for word in words:
        if word in _ALLOWED_CREDIT_ROLES:
            return _ALLOWED_CREDIT_ROLES[word]
    return ""


def _credit_key(credit):
    credit = _mapping(credit)
    ident = _first_id(credit, "id", "mbid", "artistId", "artist_id")
    name = trackmatch.fold(_text(_value(credit, "name", "artist", "label")))
    return ("id", ident) if ident else ("name", name) if name else ()


def _credit_track_match(credit, track):
    credit = _mapping(credit)
    rel_track = _first_id(credit, "releaseTrackId", "release_track_id", "trackId")
    candidate_track = _ids(track, "release_track")
    if rel_track and candidate_track:
        return rel_track == candidate_track
    wanted_title = _text(_value(credit, "trackTitle", "track_title", "title"))
    wanted_pos = _value(credit, "trackPosition", "track_position", "position", default=None)
    wanted_disc = _value(credit, "disc", "discNumber", "disc_number", default=None)
    if wanted_disc not in (None, "") and _disc(track) is not None:
        try:
            if int(str(wanted_disc).split("/", 1)[0]) != _disc(track):
                return False
        except (TypeError, ValueError):
            return False
    if wanted_pos not in (None, "") and _position(track) is not None:
        try:
            if int(str(wanted_pos).split("/", 1)[0]) != _position(track):
                return False
            return not wanted_title or _fold_title(wanted_title) == _fold_title(_title(track))
        except (TypeError, ValueError):
            pass
    return bool(wanted_title and _title(track) and
                trackmatch.title_matches(wanted_title, _title(track)))


def _active_credits(album, track):
    """Credits proven to participate in ``track`` under this album cache."""
    if not isinstance(album, dict):
        return set()
    result = set()
    for raw in album.get("credits") or ():
        credit = _mapping(raw)
        role = _credit_role(_value(credit, "role", "roles", default=""))
        if not role:
            continue
        scope = _text(_value(credit, "scope", default="")).casefold()
        if scope == "album":
            active = True
        elif scope == "track":
            active = _credit_track_match(credit, track)
        else:
            active = False
        key = _credit_key(credit)
        if active and key:
            result.add((role, key))
    return result


def _labels(album):
    if not isinstance(album, dict):
        return set()
    result = set()
    values = album.get("labels") or album.get("label") or ()
    if isinstance(values, (str, dict)):
        values = (values,)
    for raw in values:
        if isinstance(raw, str):
            name = raw
            ident = ""
        else:
            raw = _mapping(raw)
            name = _value(raw, "name", "label")
            ident = _first_id(raw, "id", "mbid", "labelId")
        key = ("id", ident) if ident else ("name", trackmatch.fold(name))
        if key[1]:
            result.add(key)
    return result


def _credit_reasons(target_credits, target_labels, candidate_album, candidate):
    reasons = []
    candidate_credits = _active_credits(candidate_album, candidate)
    for role in ("producer", "remixer", "composer", "performer"):
        if any(r == role and (r, key) in candidate_credits for r, key in target_credits):
            reasons.append("same " + role)
    if target_labels and candidate_album and target_labels & _labels(candidate_album):
        reasons.append("same label")
    return reasons


def _make_item(track, reason, score, owned=True, url=""):
    return {
        "trackId": _track_id(track) if owned else 0,
        "title": _title(track),
        "artist": _artist(track),
        "album": _album(track),
        "reason": reason,
        "score": round(float(score), 4),
        "url": _safe_url(url) if url else "",
        "owned": bool(owned),
    }


def _sort_key(item):
    return (-float(item.get("score") or 0), trackmatch.fold(item.get("artist", "")),
            trackmatch.fold(item.get("title", "")), int(item.get("trackId") or 0))


def _diverse(items, limit, artist_cap=4, album_cap=3):
    items = sorted(items, key=_sort_key)
    selected, deferred = [], []
    artists, albums = {}, {}
    for item in items:
        artist = trackmatch.fold(item.get("artist", ""))
        album = trackmatch.fold(item.get("album", ""))
        if (artist and artists.get(artist, 0) >= artist_cap) or (album and albums.get(album, 0) >= album_cap):
            deferred.append(item)
            continue
        selected.append(item)
        artists[artist] = artists.get(artist, 0) + 1
        albums[album] = albums.get(album, 0) + 1
        if len(selected) >= limit:
            return selected
    # A hard cap is preferable for a full result, but a sparse library should
    # still return every distinct connection it has.
    return selected[:limit]


def related_tracks(row, tracks, remote=(), album_info=None, known_albums=(), limit=20):
    """Rank library matches and Last.fm discoveries for one local track.

    ``remote`` is the already decoded ``similartracks.track`` sequence.  The
    result has independent ``owned`` and ``discoveries`` lists, each capped by
    ``limit``.  Every returned row has a non-empty reason; remote rows also
    have a safe Last.fm URL so the UI can offer a useful link without inventing
    a library action.
    """
    row = _prepared_track(row)
    try:
        limit = max(0, int(limit))
    except (TypeError, ValueError):
        limit = 20
    if not row or limit == 0:
        return {"owned": [], "discoveries": []}
    albums = [_mapping(x) for x in (known_albums or ()) if _mapping(x)]
    known_index = _album_index(albums)
    target_album = _mapping(album_info) if _mapping(album_info) else _album_for_track(row, known_index)
    # The supplied current album may be an effective view not present in the
    # entity cache yet.  Index it once, rather than appending it per candidate.
    album_index = _album_index(albums + ([target_album] if target_album else []))
    # These facts are identical for every candidate. Recomputing a 200-credit
    # release for every track turns a 20k library into millions of normalizations.
    target_credits = _active_credits(target_album, row)
    target_labels = _labels(target_album)
    target_rec = _ids(row, "recording")
    target_id = _track_id(row)
    target_release = _ids(row, "release") or _album_id(target_album, "release")
    target_group = _ids(row, "group") or _album_id(target_album, "group")
    target_genres = _genre_keys(_value(row, "genre", "genres"))

    # Normalize remote data once.  Duplicate Last.fm entries are common when
    # an API response contains aliases for the same artist/title.
    remote_rows = []
    remote_values = (remote.values() if isinstance(remote, dict) else remote) or ()
    remote_seen = set()
    for rank, raw in enumerate(remote_values):
        item = _mapping(raw)
        title, artist = _title(item), _remote_artist(item)
        if not title or not artist:
            continue
        rid = _first_id(item, "recordingId", "recording_id", "mbid", "musicbrainzRecordingId")
        key = ("id", rid) if rid else ("song", trackmatch.fold(artist), trackmatch.fold(title))
        if key in remote_seen:
            continue
        remote_seen.add(key)
        try:
            match = float(_value(item, "match", default=0) or 0)
        except (TypeError, ValueError):
            match = 0.0
        match = min(1.0, max(0.0, match))
        # Keep Last.fm ordering meaningful even when it omitted `match`.
        remote_rows.append((rank, item, title, artist, rid, match))

    track_rows = [_prepared_track(candidate) for candidate in (tracks or ()) if _mapping(candidate)]
    owned = []
    seen_recordings = set()
    seen_release_tracks = set()
    seen_fallback = set()
    # The old nested remote×library walk became pathological at 20k tracks and
    # 100 Last.fm entries.  These indexes retain the shared normalizer's
    # decorated-title keys, then still verify a hit with _song_match below.
    by_recording, by_song_key = {}, {}
    for candidate in track_rows:
        recording = _ids(candidate, "recording")
        if recording:
            by_recording.setdefault(recording, []).append(candidate)
        for key in trackmatch.keys(_artist(candidate), _title(candidate)):
            by_song_key.setdefault(key, []).append(candidate)

    remote_for, remote_local = {}, set()
    for rank, remote_item, title, artist, rid, match in remote_rows:
        candidates = {}
        if rid:
            for candidate in by_recording.get(rid, ()):
                candidates[id(candidate)] = candidate
        for key in trackmatch.keys(artist, title):
            for candidate in by_song_key.get(key, ()):
                candidates[id(candidate)] = candidate
        for candidate in candidates.values():
            candidate_rec = _ids(candidate, "recording")
            if rid and candidate_rec and rid == candidate_rec:
                remote_for.setdefault(_track_id(candidate), (rank, match))
                remote_local.add(rank)
            elif not (rid and candidate_rec) and _song_match({"title": title, "artist": artist}, candidate):
                remote_for.setdefault(_track_id(candidate), (rank, match))
                remote_local.add(rank)

    for candidate in track_rows:
        cid = _track_id(candidate)
        title, artist = _title(candidate), _artist(candidate)
        if cid is None or not title or not artist:
            continue
        crec = _ids(candidate, "recording")
        crelease_track = _ids(candidate, "release_track")
        if cid == target_id or (target_rec and crec and target_rec == crec) or (
                _ids(row, "release_track") and crelease_track and
                _ids(row, "release_track") == crelease_track):
            continue
        # With no recording MBID, an exact title/artist copy is the only safe
        # fallback for excluding the currently playing file.  Keep decorated
        # live/remix forms eligible; they are distinct recordings in tags.
        if not target_rec and not crec and _song_exact(row, candidate):
            continue
        fallback = (trackmatch.fold(artist), trackmatch.fold(title), trackmatch.fold(_album(candidate)))
        if crec:
            if crec in seen_recordings:
                continue
            seen_recordings.add(crec)
        elif crelease_track:
            if crelease_track in seen_release_tracks:
                continue
            seen_release_tracks.add(crelease_track)
        elif fallback in seen_fallback:
            continue
        else:
            seen_fallback.add(fallback)

        reasons, score = [], 0.0
        remote_hit = remote_for.get(cid)
        if remote_hit:
            rank, match = remote_hit
            reasons.append("last.fm")
            score += 100.0 + (match * 100.0) + max(0.0, 10.0 - rank / 10.0)

        crel, cgroup = _ids(candidate, "release"), _ids(candidate, "group")
        candidate_album = _album_for_track(candidate, album_index)
        candidate_release = crel or _album_id(candidate_album, "release")
        candidate_group = cgroup or _album_id(candidate_album, "group")
        if target_release and candidate_release and target_release == candidate_release:
            reasons.append("same release")
            score += 75
        elif target_group and candidate_group and target_group == candidate_group:
            reasons.append("same release group")
            score += 55
        elif target_album and candidate_album and target_album is candidate_album:
            reasons.append("same release")
            score += 75
        elif _album(candidate) and _album(row) and _fold_title(_album(candidate)) == _fold_title(_album(row)):
            # Title equality without an identity is useful only alongside an
            # artist/credit signal; a compilation's album title alone is weak.
            if trackmatch.artist_matches(artist, _artist(row)):
                reasons.append("same album")
                score += 28

        if _artist_ids(row) & _artist_ids(candidate):
            reasons.append("same artist")
            score += 38
        elif trackmatch.artist_matches(_artist(row), artist):
            reasons.append("same artist")
            score += 30

        genres = _genre_keys(_value(candidate, "genre", "genres"))
        if target_genres & genres:
            reasons.append("same genre")
            score += 18

        for reason in _credit_reasons(target_credits, target_labels, candidate_album, candidate):
            if reason not in reasons:
                reasons.append(reason)
                score += 48 if reason != "same label" else 13

        cyear = _year(candidate)
        if reasons and _year(row) is not None and cyear is not None:
            score += max(0.0, 8.0 - abs(_year(row) - cyear))
        if score <= 0 or not reasons:
            continue
        owned.append(_make_item(candidate, "; ".join(reasons), score, True))

    # An unknown remote row is a discovery; an owned match is represented in
    # `owned` only, even when it appeared in Last.fm's response.
    discoveries = []
    for rank, item, title, artist, rid, match in remote_rows:
        if rank in remote_local or (target_rec and rid and target_rec == rid):
            continue
        score = 100.0 + match * 100.0 + max(0.0, 10.0 - rank / 10.0)
        discoveries.append(_make_item({"title": title, "artist": artist,
                                       "album": _text(_value(item, "album", "albumTitle"))},
                                      "last.fm", score, False,
                                      _remote_url(item, artist, title)))

    return {"owned": _diverse(owned, limit), "discoveries": _diverse(discoveries, limit, 3, 2)}


__all__ = ["related_tracks"]
