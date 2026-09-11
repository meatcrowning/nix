#!/usr/bin/env python3
"""Offline checks: the artist survives a release that cannot be identified."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ.pop('WAYLAND_DISPLAY', None)
os.environ.pop('DISPLAY', None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / 'pylib'))

from artistinfo import ArtistInfo, life_span  # noqa: E402

ARTIST = {
    'id': 'artist-1', 'name': 'Steve Reich', 'sort-name': 'Reich, Steve',
    'type': 'Person', 'area': {'name': 'United States'},
    'life-span': {'begin': '1936-10-03', 'ended': False},
    'relations': [{'type': 'wikidata',
                   'url': {'resource': 'https://www.wikidata.org/wiki/Q206820'}}],
}


def pure():
    # A tagged artist ID needs no search at all.
    calls = []

    def fetch(url):
        calls.append(url)
        if '/artist/artist-1' in url:
            return ARTIST
        raise AssertionError(url)

    facts = ArtistInfo(fetch).resolve('Steve Reich', ['artist-1'])
    assert facts['name'] == 'Steve Reich' and facts['years'] == '1936-', facts
    assert facts['area'] == 'United States' and facts['type'] == 'Person', facts
    assert facts['links'][0]['type'] == 'wikidata', facts
    assert len(calls) == 1, calls

    # Without an ID the name search must come back as the same name.
    def searching(url):
        calls.append(url)
        if 'query=' in url:
            return {'artists': [{'id': 'artist-9', 'name': 'Steve Reichenbach', 'score': 100},
                                {'id': 'artist-1', 'name': 'Steve Reich', 'score': 97}]}
        if '/artist/artist-1' in url:
            return ARTIST
        raise AssertionError(url)

    assert ArtistInfo(searching).resolve('Steve Reich')['id'] == 'artist-1'

    def wrong(url):
        if 'query=' in url:
            return {'artists': [{'id': 'artist-9', 'name': 'Steve Reichenbach', 'score': 100}]}
        raise AssertionError(url)

    assert ArtistInfo(wrong).resolve('Steve Reich') == {}, 'a near name is not the artist'

    def weak(url):
        if 'query=' in url:
            return {'artists': [{'id': 'artist-1', 'name': 'Steve Reich', 'score': 42}]}
        raise AssertionError(url)

    assert ArtistInfo(weak).resolve('Steve Reich') == {}, 'a weak hit is not the artist'

    # A dead tagged ID falls through to the search rather than raising.
    def broken(url):
        if '/artist/dead' in url:
            raise RuntimeError('HTTP Error 404: Not Found')
        if 'query=' in url:
            return {'artists': [{'id': 'artist-1', 'name': 'Steve Reich', 'score': 100}]}
        return ARTIST

    assert ArtistInfo(broken).resolve('Steve Reich', ['dead'])['id'] == 'artist-1'
    assert life_span({'begin': '1975-01-01', 'end': '1999', 'ended': True}) == '1975-1999'
    assert life_span({}) == ''


def coordinated():
    with tempfile.TemporaryDirectory() as td:
        for key in ('DATA', 'STATE', 'CACHE', 'CONFIG', 'RUNTIME'):
            os.environ['XDG_' + key + ('_DIR' if key == 'RUNTIME' else '_HOME')] = td + '/' + key
        import main
        import albuminfo
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.instance() or QCoreApplication([])
        main.DATA = Path(td) / 'data'
        main.DB_PATH = main.DATA / 'library.db'
        con = main.open_db()
        con.execute('''INSERT INTO tracks
          (id,path,mtime,size,title,artist,album,album_artist,track,disc,duration,genre,identity_json,added_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (1, '/fixture/octet/1.flac', 1, 1, 'Octet', 'Steve Reich', 'Octet',
           'Steve Reich', 1, 1, 2475, 'classical',
           json.dumps({'scanned': True, 'artistIds': ['artist-1']}), time.time()))
        con.commit()

        released = []

        def fetch(url):
            released.append(url)
            if '/artist/artist-1' in url:
                return ARTIST
            if 'wikidata.org' in url:
                return {'entities': {'Q206820': {'sitelinks': {'enwiki': {'title': 'Steve Reich'}}}}}
            if 'wikipedia.org' in url:
                return {'extract': 'An American composer.',
                        'content_urls': {'desktop': {'page': 'https://en.wikipedia.org/wiki/Steve_Reich'}}}
            # Every release request fails, exactly as a MusicBrainz 503 does.
            raise RuntimeError('HTTP Error 503: Service Temporarily Unavailable')

        def lastfm(method, params):
            return {}

        with patch.object(albuminfo.threading.Thread, 'start'):
            provider = main.NowPlayingMetadata(None, fetch_json=fetch, lastfm_call=lastfm)
        state = provider._resolve(1)
        assert state['albumError'].startswith('HTTP Error 503'), state['albumError']
        artist = state['album'].get('artistInfo') or {}
        assert artist.get('name') == 'Steve Reich', state['album']
        assert artist['years'] == '1936-' and artist['area'] == 'United States', artist
        assert artist['description'] == 'An American composer.', artist
        assert artist['descriptionSource'] == 'wikipedia', artist

        # A second album by the same artist reads the shared download.
        count = len(released)
        con.execute('''INSERT INTO tracks
          (id,path,mtime,size,title,artist,album,album_artist,track,disc,duration,genre,identity_json,added_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (2, '/fixture/drumming/1.flac', 1, 1, 'Drumming', 'Steve Reich', 'Drumming',
           'Steve Reich', 1, 1, 3600, 'classical', json.dumps({'scanned': True}), time.time()))
        con.commit()
        provider.invalidate_library()
        second = provider._resolve(2)
        assert (second['album'].get('artistInfo') or {}).get('id') == 'artist-1', second['album']
        assert not [u for u in released[count:] if '/artist/' in u or 'wiki' in u], released[count:]

        # A compilation credit is not a person and must not be looked up.
        con.execute("""INSERT INTO tracks
          (id,path,mtime,size,title,artist,album,album_artist,track,disc,duration,genre,identity_json,added_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (3, '/fixture/comp/1.flac', 1, 1, 'a song', 'somebody', 'a compilation',
           'Various Artists', 1, 1, 200, '', json.dumps({'scanned': True}), time.time()))
        con.commit()
        provider.invalidate_library()
        count = len(released)
        third = provider._resolve(3)
        assert not third['album'].get('artistInfo'), third['album']
        assert not [u for u in released[count:] if '/artist/' in u], released[count:]

        # Clearing the album's cache drops the shared artist download too.
        provider._apply_command(1, 'clear', None)
        cleared = provider._cached_state(1)
        assert not cleared['album'].get('artistInfo'), cleared['album']
    print('artist-info-test: ok')


pure()
coordinated()
