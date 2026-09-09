#!/usr/bin/env python3
"""Fixture-only regression checks for the pure related-music ranker."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relatedmusic import related_tracks  # noqa: E402


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def track(tid, title, artist="North Star", album="Edition", **extra):
    value = {"id": tid, "title": title, "artist": artist, "album": album}
    value.update(extra)
    return value


def run():
    target = track(1, "Anchor", year=2020, genre="Hip-Hop",
                   identity_json='{"releaseId":"edition-1", "releaseGroupId":"group-1", "recordingId":"rec-1"}')
    edition = {
        "title": "Edition", "artist": "North Star",
        "musicbrainzReleaseId": "edition-1", "musicbrainzReleaseGroupId": "group-1",
        "credits": [{"id": "producer-1", "name": "P", "role": "producer", "scope": "album"}],
        "tracks": [{"position": 1, "title": "Anchor", "recordingId": "rec-1"},
                   {"position": 2, "title": "B", "recordingId": "rec-2"}],
    }
    compilation = {
        "title": "Huge Compilation", "artist": "Various Artists",
        "musicbrainzReleaseId": "comp-1",
        "credits": [{"id": "composer-1", "name": "C", "role": "composer",
                     "scope": "track", "trackTitle": "Other"}],
        "tracks": [{"position": 4, "title": "Compilation Song"}],
    }

    local = [
        target,
        track(2, "B", year=2020, genre="rap", identity_json='{"releaseId":"edition-1", "recordingId":"rec-2"}'),
        # Same year alone must not manufacture a relationship.
        track(3, "Unrelated", artist="South Star", album="Different", year=2020, genre="Classical"),
        track(4, "Compilation Song", artist="Various Artists", album="Huge Compilation",
              year=2020, genre="Classical", identity_json='{"releaseId":"comp-1"}'),
    ]
    result = related_tracks(target, local, album_info=edition, known_albums=[edition, compilation])
    owned = {item["trackId"]: item for item in result["owned"]}
    check(2 in owned and "same release" in owned[2]["reason"], owned)
    check(3 not in owned, owned)
    check(4 not in owned, owned)

    # The bounded alias table treats rap and hip-hop as one genre, without
    # making an unrelated same-year track eligible.
    genre_result = related_tracks(target, [target, track(5, "Rap Song", artist="East Star",
                                                         album="Other", genre="rap", year=1999)])
    check("same genre" in genre_result["owned"][0]["reason"], genre_result)

    remote = [
        {"name": "Local Song", "artist": {"name": "North Star"}, "match": "0.8"},
        {"name": "Local Song", "artist": {"name": "North Star"}, "match": "0.7"},
        {"name": "New Song", "artist": {"name": "Far Star"}, "match": "0.91",
         "url": "javascript:alert(1)"},
        {"name": "Broken", "artist": {}, "url": "https://example.invalid/broken"},
        "malformed",
    ]
    with_local = related_tracks(target, local + [track(6, "Local Song", artist="North Star")], remote=remote)
    ids = [item["trackId"] for item in with_local["owned"]]
    check(ids.count(6) == 1, with_local)
    check(not any(item["title"] == "Local Song" for item in with_local["discoveries"]), with_local)
    discoveries = [item for item in with_local["discoveries"] if item["title"] == "New Song"]
    check(len(discoveries) == 1 and discoveries[0]["trackId"] == 0, with_local)
    check(discoveries[0]["url"].startswith("https://www.last.fm/music/"), discoveries[0])

    # Album-scoped credit evidence is bounded to its release.  A track-scoped
    # compilation credit for another title cannot leak to this track.
    credit_album = {
        "title": "Credit Album", "artist": "Credit Artist",
        "musicbrainzReleaseId": "credit-1",
        "credits": [{"id": "composer-1", "name": "C", "role": "composer",
                     "scope": "album"}],
    }
    credit_local = [target, track(7, "Credit Song", artist="Credit Artist", album="Credit Album",
                                  identity_json='{"releaseId":"credit-1"}')]
    credit_result = related_tracks(target, credit_local, album_info=edition,
                                  known_albums=[edition, credit_album])
    check(7 not in {x["trackId"] for x in credit_result["owned"]}, credit_result)

    # Track credits include the disc, so disc 2/track 1 cannot inherit disc
    # 1/track 1's person merely because their positions are equal.  An
    # explicit release id likewise blocks a same-title cache from another
    # edition.
    multidisc = {
        "title": "Multi", "artist": "North Star", "musicbrainzReleaseId": "edition-1",
        "credits": [{"id": "remix-1", "name": "R", "role": "remixer", "scope": "track",
                     "disc": 1, "position": 1}],
    }
    wrong_edition = {"title": "Multi", "artist": "South Star",
                     "musicbrainzReleaseId": "edition-other",
                     "credits": [{"id": "producer-1", "name": "P", "role": "producer", "scope": "album"}]}
    md_local = [target, track(8, "Disc Two", artist="South Star", album="Multi", disc=2, track=1,
                              identity_json='{"releaseId":"edition-other"}'),
                track(9, "Anchor", artist="South Star", album="Edition", year=2020,
                      identity_json='{"releaseId":"edition-other"}')]
    md_result = related_tracks(target, md_local, album_info=multidisc,
                               known_albums=[multidisc, wrong_edition])
    check(8 not in {x["trackId"] for x in md_result["owned"]}, md_result)
    check(9 not in {x["trackId"] for x in md_result["owned"]}, md_result)

    # A group-only tag identifies an album concept, not one cached edition.
    # Competing edition credits must therefore stay unavailable until a
    # concrete release is known.
    group_target = track(10, "Group Target", artist="One", album="Concept",
                         identity_json='{"releaseGroupId":"concept-group"}')
    group_candidate = track(11, "Group Candidate", artist="Two", album="Concept",
                            identity_json='{"releaseGroupId":"concept-group"}')
    group_editions = [
        {"musicbrainzReleaseId": "concept-a", "musicbrainzReleaseGroupId": "concept-group",
         "credits": [{"id": "shared", "name": "S", "role": "producer", "scope": "album"}]},
        {"musicbrainzReleaseId": "concept-b", "musicbrainzReleaseGroupId": "concept-group",
         "credits": [{"id": "shared", "name": "S", "role": "producer", "scope": "album"}]},
    ]
    group_result = related_tracks(group_target, [group_target, group_candidate],
                                  known_albums=group_editions)
    check(group_result["owned"] and group_result["owned"][0]["reason"] == "same release group",
          group_result)

    # Instrument attributes normalized by releaseinfo are source-backed
    # performer evidence, not a guessed genre/name association.
    instrument_target = track(12, "String One", artist="Three", album="A",
                              identity_json='{"releaseId":"inst-a"}')
    instrument_candidate = track(13, "String Two", artist="Four", album="B",
                                 identity_json='{"releaseId":"inst-b"}')
    instrument_albums = [
        {"musicbrainzReleaseId": "inst-a", "credits": [{"id": "g", "name": "G", "role": "instrument guitar", "scope": "album"}]},
        {"musicbrainzReleaseId": "inst-b", "credits": [{"id": "g", "name": "G", "role": "instrument guitar", "scope": "album"}]},
    ]
    instrument_result = related_tracks(instrument_target,
                                       [instrument_target, instrument_candidate],
                                       known_albums=instrument_albums)
    check("same performer" in instrument_result["owned"][0]["reason"], instrument_result)

    # A shared conceptual album never transfers edition-specific credits.
    distinct_editions = [dict(group_editions[0]), dict(group_editions[1])]
    distinct_editions[1]["credits"] = []
    concrete_a = dict(group_target, identity_json='{"releaseId":"concept-a"}')
    concrete_b = dict(group_candidate, identity_json='{"releaseId":"concept-b"}')
    concrete = related_tracks(concrete_a, [concrete_a, concrete_b], known_albums=distinct_editions)
    check("same producer" not in concrete["owned"][0]["reason"], concrete)
    # Known, conflicting recording IDs cannot be joined on the same title.
    collision = track(80, "Duplicate Title", artist="Artist", identity_json='{"recordingId":"local-rec"}')
    remote_collision = related_tracks(target, [target, collision], remote=[
        {"name": "Duplicate Title", "artist": "Artist", "mbid": "different-rec"}])
    check(remote_collision["discoveries"], remote_collision)

    # Diversity keeps a long run of one artist/release from taking the pane.
    many = [target] + [track(20 + i, "Song %d" % i, album="Edition", genre="Hip-Hop")
                       for i in range(7)] + [track(99, "Other Artist Song", artist="Other Star",
                                                   album="Other", genre="Hip-Hop")]
    diverse = related_tracks(target, many, limit=20)
    selected = diverse["owned"]
    check(len(selected) <= 7, selected)
    check(any(x["artist"] == "Other Star" for x in selected), selected)
    check(len({x["artist"] for x in selected}) > 1, selected)

    check(related_tracks({}, None, remote=[None, {}]) == {"owned": [], "discoveries": []}, "empty input")
    check(related_tracks(target, [], remote=[{"name": "No URL", "artist": "A"}], limit="bad")["discoveries"],
          "malformed limit")
    print("related-music-test: ok")


if __name__ == "__main__":
    run()
