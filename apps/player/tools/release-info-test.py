#!/usr/bin/env python3
"""Focused fixture checks for the pure release information provider."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from releaseinfo import ReleaseInfo, read_identity  # noqa: E402


RID = "release-漢字"
RGID = "group-1"
REC1 = "recording-1"
REC2 = "recording-2"


def release(release_id=RID, title="Álbum: A/B", artist="Björk", alternate=False):
    return {
        "id": release_id, "title": title, "date": "2001-02-03", "country": "IS",
        "status": "Official", "barcode": "123", "artist-credit": [
            {"name": artist, "artist": {"id": "artist-1", "name": artist}}],
        "release-group": {"id": RGID, "first-release-date": "2000-01-01",
                          "relations": [{"type": "wikipedia", "url": {"resource": "https://en.wikipedia.org/wiki/Album"}}]},
        "label-info": [{"catalog-number": "CAT-1", "label": {"id": "label-1", "name": "Label"}}],
        "relations": [{"type": "producer", "artist": {"id": "producer-1", "name": "Producer"}}],
        "media": [{"position": 1, "format": "CD", "track-count": 2, "tracks": [
            {"position": 1, "title": "Song One", "length": 180000,
             "recording": {"id": REC1, "title": "Song One", "relations": [
                 {"type": "instrument", "attributes": ["guitar"],
                  "artist": {"id": "guitar-1", "name": "Guitarist"}}]}},
            {"position": 2, "title": "Song Two", "length": 210000,
             "recording": {"id": REC2, "title": "Song Two"}},
        ]}],
    }


GROUP = {"id": RGID, "first-release-date": "2000-01-01", "relations": [
    {"type": "wikidata", "url": {"resource": "https://www.wikidata.org/wiki/Q1"}},
]}


def row(**changes):
    base = {"id": 5, "title": "Song One", "artist": "Björk", "album_artist": "Björk",
            "album": "Álbum: A/B", "duration": 180, "track": 1, "disc": 1,
            "identity_json": ""}
    base.update(changes)
    return base


def fixture_fetch(routes, seen):
    def fetch(url):
        seen.append(url)
        decoded = unquote(url)
        for needle, result in routes.items():
            if needle in decoded:
                return result
        raise AssertionError("unexpected URL: " + url)
    return fetch


def test_ids_and_credits():
    seen = []
    provider = ReleaseInfo(fixture_fetch({f"/release/{RID}": release(), f"/release-group/{RGID}": GROUP}, seen))
    result = provider.resolve(row(identity_json='{"releaseId":"release-漢字","recordingId":"recording-1"}'), [])
    assert result["status"] == "ready"
    assert result["recordingId"] == REC1
    album = result["album"]
    assert album["musicbrainzReleaseId"] == RID and album["labels"][0]["catalogNumber"] == "CAT-1"
    assert album["media"][0]["trackCount"] == 2 and album["tracks"][0]["duration"] == 180
    assert {credit["role"] for credit in album["credits"]} >= {"artist", "producer", "instrument guitar"}
    assert next(c for c in album["credits"] if c["role"] == "instrument guitar")["disc"] == 1
    assert album["artistIds"] == ["artist-1"]
    assert {link["type"] for link in album["links"]} == {"wikipedia", "wikidata"}
    assert any("recording-level-rels" in url for url in seen)


def test_preferred_id_beats_tag():
    seen = []
    provider = ReleaseInfo(fixture_fetch({"/release/manual": release("manual"), f"/release-group/{RGID}": GROUP}, seen))
    result = provider.resolve(row(identity_json='{"releaseId":"stale"}'), [], "manual")
    assert result["status"] == "ready" and result["album"]["musicbrainzReleaseId"] == "manual"
    assert any("/release/manual" in url for url in seen) and not any("/release/stale" in url for url in seen)


def test_search_escapes_and_never_guesses_first():
    seen = []
    wrong = release("wrong", title="Álbum: A/B", artist="Björk")
    right = release("right")
    routes = {"/release/?": {"releases": [{"id": "wrong"}, {"id": "right"}]},
              "/release/wrong": wrong, "/release/right": right,
              f"/release-group/{RGID}": GROUP}
    provider = ReleaseInfo(fixture_fetch(routes, seen))
    tracks = [row(id=6, title="Song Two", track=2, duration=210)]
    # Equal detailed candidates are explicitly ambiguous, rather than picking
    # the first release attached to a matching recording/search result.
    result = provider.resolve(row(), tracks)
    assert result["status"] == "ambiguous" and [x["id"] for x in result["candidates"]] == ["wrong", "right"]
    search_url = next(url for url in seen if "/release/?" in url)
    assert "%C3%81lbum" in search_url and "%5C%3A" in search_url and "%5C%2F" in search_url


def test_group_tag_constrains_fallback_search():
    wrong = release("wrong")
    wrong["release-group"] = {"id": "other-group"}
    right = release("right")
    seen = []
    provider = ReleaseInfo(fixture_fetch({"/release/?": {"releases": [{"id": "wrong"}, {"id": "right"}]},
                                          "/release/wrong": wrong, "/release/right": right,
                                          f"/release-group/{RGID}": GROUP}, seen))
    result = provider.resolve(row(identity_json='{"releaseGroupId":"group-1"}'), [])
    assert [candidate["id"] for candidate in result["candidates"]] == ["right"]
    search_url = next(url for url in seen if "/release/?" in url)
    assert "rgid%3A%22group%5C-1%22" in search_url


def test_sparse_tracks_do_not_reject_release():
    seen = []
    provider = ReleaseInfo(fixture_fetch({"/release/?": {"releases": [{"id": RID}]},
                                          f"/release/{RID}": release(), f"/release-group/{RGID}": GROUP}, seen))
    result = provider.resolve(row(), [])
    assert result["status"] == "ready" and result["candidates"][0]["trackCount"] == 2


def test_multidisc_credit_positions_stay_distinct():
    multi = release()
    multi["media"].append({"position": 2, "format": "CD", "track-count": 1, "tracks": [
        {"position": 1, "title": "Song One", "length": 180000,
         "recording": {"id": "recording-disc-two", "title": "Song One", "relations": [
             {"type": "instrument", "attributes": ["guitar"],
              "artist": {"id": "guitar-1", "name": "Guitarist"}}]}},
    ]})
    seen = []
    provider = ReleaseInfo(fixture_fetch({f"/release/{RID}": multi,
                                          f"/release-group/{RGID}": GROUP}, seen))
    result = provider.resolve(row(identity_json='{"releaseId":"release-漢字"}'), [])
    guitars = [credit for credit in result["album"]["credits"] if credit["role"] == "instrument guitar"]
    assert [(credit["disc"], credit["trackPosition"]) for credit in guitars] == [(1, 1), (2, 1)]


def test_tagged_recording_mismatch_does_not_fall_back_to_title():
    seen = []
    provider = ReleaseInfo(fixture_fetch({"/release/?": {"releases": [{"id": RID}]},
                                          f"/release/{RID}": release(),
                                          f"/release-group/{RGID}": GROUP}, seen))
    result = provider.resolve(row(identity_json='{"recordingId":"different-recording"}'), [])
    assert result["status"] == "ambiguous"
    assert result["candidates"][0]["confidence"] < .82


def test_missing_observed_disc_cannot_auto_match():
    seen = []
    provider = ReleaseInfo(fixture_fetch({"/release/?": {"releases": [{"id": RID}]},
                                          f"/release/{RID}": release(),
                                          f"/release-group/{RGID}": GROUP}, seen))
    result = provider.resolve(row(disc=2), [])
    assert result["status"] == "ambiguous"
    assert result["candidates"][0]["confidence"] == .5


def test_position_recording_requires_title_when_known():
    album = {"tracks": [{"disc": 1, "position": 1, "title": "Other Song", "recordingId": "wrong"},
                        {"disc": 1, "position": 2, "title": "Song One", "recordingId": "right"}]}
    from releaseinfo import _recording_id  # private pure helper, exercised at its boundary
    assert _recording_id(row(track=1), album) == "right"


def test_required_lookup_failure_propagates():
    provider = ReleaseInfo(lambda _url: (_ for _ in ()).throw(OSError("offline")))
    try:
        provider.resolve(row(identity_json='{"releaseId":"known"}'), [])
    except OSError as error:
        assert str(error) == "offline"
    else:
        raise AssertionError("required release lookup did not propagate failure")


def test_optional_group_failure_keeps_release_details():
    seen = []
    provider = ReleaseInfo(fixture_fetch({f"/release/{RID}": release()}, seen))
    result = provider.resolve(row(identity_json='{"releaseId":"release-漢字"}'), [])
    assert result["status"] == "ready" and result["album"]["tracks"]
    assert result["album"]["error"] == "unexpected URL: " + next(
        url for url in seen if "/release-group/" in url)


def test_duck_typed_tag_families():
    class Audio:
        tags = {"TXXX:MusicBrainz Album Id": ["album-id"],
                "TXXX:MusicBrainz Artist Id": ["a;b", "b"],
                "TXXX:MusicBrainz Track Id": ["recording-id"]}
    assert read_identity(Audio()) == {"releaseId": "album-id", "releaseGroupId": "", "recordingId": "recording-id", "releaseTrackId": "", "artistIds": ["a", "b"]}
    # FLAC/Vorbis and APEv2 are both mapping-style but differ in customary
    # casing; neither fixture imports mutagen.
    flac = {"MUSICBRAINZ_ALBUMID": ["flac-album"],
            "MusicBrainz_ReleaseGroupId": ["flac-group"],
            "musicbrainz_trackid": ["flac-recording"],
            "MUSICBRAINZ_ALBUMARTISTID": ["flac-artist"]}
    ape = {"MusicBrainz Album Id": "ape-album",
           "MUSICBRAINZ_RELEASETRACKID": "ape-track"}
    assert read_identity(flac)["releaseGroupId"] == "flac-group"
    assert read_identity(flac)["recordingId"] == "flac-recording"
    assert read_identity(flac)["artistIds"] == []
    assert read_identity(flac)["albumArtistIds"] == ["flac-artist"]
    assert read_identity(ape)["releaseId"] == "ape-album"
    assert read_identity(ape)["releaseTrackId"] == "ape-track"
    mp4 = {"----:com.apple.iTunes:MusicBrainz Album Id": [b"mp4-album"],
           "----:com.apple.iTunes:MusicBrainz Release Track Id": [b"rt"],
           "----:com.apple.iTunes:MusicBrainz Artist Id": [b"mp4-artist"]}
    got = read_identity(mp4)
    assert got["releaseId"] == "mp4-album" and got["releaseTrackId"] == "rt"
    assert got["artistIds"] == ["mp4-artist"]

    class Ufid:
        data = b"ufid-recording"
    class UfidAudio:
        tags = {"UFID:http://musicbrainz.org": Ufid()}
    assert read_identity(UfidAudio())["recordingId"] == "ufid-recording"


def test_compilation_artist_ids_stay_scoped():
    tags = {"musicbrainz_artistid": ["track-artist"],
            "musicbrainz_albumartistid": ["various-artists"]}
    got = read_identity(tags)
    assert got["artistIds"] == ["track-artist"]
    assert got["albumArtistIds"] == ["various-artists"]


def main():
    for test in (test_ids_and_credits, test_preferred_id_beats_tag,
                 test_search_escapes_and_never_guesses_first,
                 test_group_tag_constrains_fallback_search,
                 test_sparse_tracks_do_not_reject_release,
                 test_multidisc_credit_positions_stay_distinct,
                 test_tagged_recording_mismatch_does_not_fall_back_to_title,
                 test_missing_observed_disc_cannot_auto_match,
                 test_position_recording_requires_title_when_known,
                 test_required_lookup_failure_propagates,
                 test_optional_group_failure_keeps_release_details,
                 test_duck_typed_tag_families,
                 test_compilation_artist_ids_stay_scoped):
        test()
    print("release info: ok")


if __name__ == "__main__":
    main()
