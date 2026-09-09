#!/usr/bin/env python3
"""Headless, fixture-only regression test for now-playing web metadata."""

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main  # noqa: E402


def check(ok, message):
    if not ok:
        raise AssertionError(message)


def track(con, tid, title="Grey Geisha"):
    con.execute("""INSERT INTO tracks
      (id,path,mtime,size,title,artist,album,album_artist,date,year,orig_year,
       genre,duration,added_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (tid, f"/fixture/{tid}.flac", 1, 1, title, "Tim Hecker",
         "Instrumental Tourist", "Tim Hecker", "2012", 2012, 2012,
         "Ambient", 258.0, time.time()))


def fixtures(url):
    if "/recording/" in url:
        return {"recordings": [{
            "id": "rec-1", "title": "Grey Geisha", "length": 258000,
            "artist-credit": [{"name": "Tim Hecker", "joinphrase": ""}],
            "releases": [{"title": "Instrumental Tourist",
                          "release-group": {"id": "rg-1"}}],
        }]}
    if "/release-group/rg-1" in url:
        return {"title": "Instrumental Tourist", "first-release-date": "2012-09-10",
                "primary-type": "Album", "secondary-types": ["Collaboration"],
                "relations": [{"type": "wikidata",
                               "url": {"resource": "https://www.wikidata.org/wiki/Q1"}}]}
    if "Special:EntityData/Q1" in url:
        return {"entities": {"Q1": {"sitelinks": {"enwiki": {"title": "Instrumental Tourist"}}}}}
    if "/page/summary/" in url:
        return {"title": "Instrumental Tourist", "extract": "A collaborative studio album.",
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Instrumental_Tourist"}}}
    raise AssertionError("unexpected network request: " + url)


def lastfm(_method, _params):
    return {"similartracks": {"track": [
        {"name": "Virginal II", "artist": {"name": "Tim Hecker"}},
    ]}}


def run():
    with tempfile.TemporaryDirectory() as td:
        main.DATA = Path(td) / "data"
        main.DB_PATH = main.DATA / "library.db"
        con = main.open_db()
        track(con, 1)
        track(con, 2, "Virginal II")
        track(con, 3, "Other")
        con.commit()
        provider = main.NowPlayingMetadata(None, fetch_json=fixtures, lastfm_call=lastfm)
        state = provider._resolve(1)
        check(state["status"] == "ready", state)
        check(state["match"]["id"] == "rec-1", state)
        check(state["album"]["description"] == "A collaborative studio album.", state)
        check(state["album"]["sources"] == ["musicbrainz", "wikipedia"], state)
        check(state["similar"][0]["trackId"] == 2, state)
        check(state["similar"][0]["reason"] == "last.fm", state)

        check(provider.edit(1, "album", {"description": "my correction"}), "edit refused")
        check(provider._cached_state(1)["album"]["description"] == "my correction", "override absent")
        check(provider.revert(1, "album"), "revert refused")
        check(provider._cached_state(1)["album"]["description"].startswith("A collaborative"), "revert absent")

        # A Last.fm outage retains useful local recommendations and records the
        # failure explicitly rather than presenting the fallback as web data.
        provider._lastfm_call = lambda *_: (_ for _ in ()).throw(RuntimeError("offline"))
        state = provider._resolve(1, True)
        check(state["similarFallback"], state)
        check("offline" in state["error"], state)

        # Low-confidence MusicBrainz results are choices, never silent matches.
        def ambiguous(url):
            if "/recording/" in url:
                return {"recordings": [
                    {"id": "maybe-1", "title": "Grey Geisha", "length": 200000,
                     "artist-credit": [{"name": "Someone Else"}], "releases": []},
                    {"id": "maybe-2", "title": "Grey Geisha", "length": 201000,
                     "artist-credit": [{"name": "Another Artist"}], "releases": []},
                ]}
            raise AssertionError(url)
        con.execute("DELETE FROM web_entity_matches")
        con.execute("DELETE FROM web_metadata")
        con.commit()
        provider._fetch_json_fn = ambiguous
        state = provider._resolve(1, True)
        check(state["status"] == "ambiguous", state)
        check(len(state["candidates"]) == 2, state)
        check(provider.choose(1, "maybe-1"), "candidate choice refused")
        chosen = con.execute("SELECT entity_id,manual FROM web_entity_matches").fetchone()
        check(tuple(chosen) == ("maybe-1", 1), chosen)
        con.close()

        # Upgrade the short-lived development schema without losing the newest
        # cached response for an entity.
        main.DATA = Path(td) / "old-data"
        main.DB_PATH = main.DATA / "library.db"
        main.DATA.mkdir(parents=True)
        old = __import__("sqlite3").connect(main.DB_PATH)
        old.execute("""CREATE TABLE web_metadata (
          cache_key TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
          body_json TEXT NOT NULL DEFAULT '{}', fetched_at REAL, expires_at REAL,
          error TEXT, PRIMARY KEY (cache_key,kind,source))""")
        old.execute("INSERT INTO web_metadata VALUES (?,?,?,?,?,?,?)",
                    ("album:key", "album", "old", '{"title":"old"}', 1, 2, None))
        old.execute("INSERT INTO web_metadata VALUES (?,?,?,?,?,?,?)",
                    ("album:key", "album", "new", '{"title":"new"}', 2, 3, None))
        old.commit()
        old.close()
        upgraded = main.open_db()
        pk = [r["name"] for r in upgraded.execute("PRAGMA table_info(web_metadata)") if r["pk"]]
        check(pk == ["cache_key", "kind"], pk)
        row = upgraded.execute("SELECT source,body_json FROM web_metadata").fetchone()
        check(tuple(row) == ("new", '{"title":"new"}'), row)
        upgraded.close()
    print("now-info-test: ok")


if __name__ == "__main__":
    run()
