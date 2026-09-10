#!/usr/bin/env python3
"""Offline integration checks: shared releases, corrections, retries and locks."""
import json
import io
import os
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.error
from pathlib import Path
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ.pop('WAYLAND_DISPLAY', None)
os.environ.pop('DISPLAY', None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    with tempfile.TemporaryDirectory() as td:
        for key in ('DATA', 'STATE', 'CACHE', 'CONFIG', 'RUNTIME'):
            os.environ['XDG_' + key + ('_DIR' if key == 'RUNTIME' else '_HOME')] = td + '/' + key
        import main
        import albuminfo
        import infostore as store
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance() or QCoreApplication([])
        main.DATA = Path(td) / 'data'
        main.DB_PATH = main.DATA / 'library.db'
        con = main.open_db()
        for tid, title in ((1, 'one'), (2, 'two'), (3, 'three')):
            con.execute('''INSERT INTO tracks
              (id,path,mtime,size,title,artist,album,album_artist,track,disc,duration,genre,identity_json,added_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (tid, f'/fixture/album/{tid}.flac', 1, 1, title, 'artist', 'album', 'artist', tid, 1, 180,
               'ambient', json.dumps({'scanned': True, 'releaseId': 'release-1'}), time.time()))
        con.commit()
        calls = []
        partial = False
        offline = False
        def fetch(url):
            nonlocal partial, offline
            calls.append(url)
            # A concurrent writer must succeed during every external fetch.
            with sqlite3.connect(main.DB_PATH, timeout=.1) as writer:
                writer.execute('UPDATE tracks SET size=size WHERE id=1')
            if offline:
                raise RuntimeError('offline')
            if '/release-group/' in url:
                if partial:
                    raise RuntimeError('group unavailable')
                return {'id': 'group-1', 'first-release-date': '1999-01-01'}
            if '/release/release-1' in url:
                return {'id': 'release-1', 'title': 'album', 'date': '2004-01-01',
                        'release-group': {'id': 'group-1'},
                        'artist-credit': [{'name': 'artist', 'artist': {'id': 'artist-1', 'name': 'artist'}}],
                        'media': [{'position': 1, 'format': 'CD', 'track-count': 3, 'tracks': [
                            {'position': i, 'title': title, 'recording': {'id': f'rec-{i}', 'title': title}}
                            for i, title in ((1, 'one'), (2, 'two'), (3, 'three'))]}]}
            raise AssertionError(url)
        def similar(*args):
            with sqlite3.connect(main.DB_PATH, timeout=.1) as writer:
                writer.execute('UPDATE tracks SET size=size WHERE id=1')
            return {'similartracks': {'track': [{'name': 'two', 'artist': {'name': 'artist'}}]}}
        # Suppress background workers for deterministic direct integration calls.
        with patch.object(albuminfo.threading.Thread, 'start'):
            provider = main.NowPlayingMetadata(None, fetch_json=fetch, lastfm_call=similar)
        state = provider._resolve(1)
        assert state['status'] == 'ready', state
        assert state['album']['firstReleaseDate'] == '1999-01-01'
        assert state['album']['releaseDate'] == '2004-01-01'
        assert state['similar'][0]['trackId'] == 2, state
        count = len(calls)
        second = provider._resolve(2)
        assert state["recordingId"] == "rec-1" and second["recordingId"] == "rec-2"
        assert len(calls) == count, 'another song fetched the same album again'
        # Cached facts must arrive before tags/indexing/Last.fm can block.
        published = []
        with patch.object(provider, '_publish', side_effect=lambda s: published.append(s)), \
             patch.object(provider, '_load_identity', side_effect=lambda _c, r: (
                 published and published[0]['album']['title'] == 'album' and r)):
            provider._resolve(2)
        assert published[0]['album']['title'] == 'album'
        # Old empty Wikipedia-only misses do not block the expanded policy.
        con.execute("DELETE FROM music_info_cache WHERE kind='prose-v2'")
        store.cache_put(con, 'release:release-1', 'prose', {}, 30 * 86400)
        wiki = {'album': {'name': 'album', 'artist': 'artist',
                         'url': 'https://www.last.fm/music/artist/album',
                         'wiki': {'content': 'A sourced album write-up.'}}}
        prose_calls = []
        def with_prose(method, params):
            prose_calls.append(method)
            return wiki if method == 'album.getInfo' else similar(method, params)
        with patch.object(provider, '_lastfm_call', side_effect=with_prose):
            enriched = provider._resolve(1)
            assert enriched['album']['description'] == 'A sourced album write-up.'
            assert enriched['album']['sources'][-1] == 'last.fm'
            provider._resolve(2)
        assert prose_calls.count('album.getInfo') == 1, 'album prose was fetched per song'
        with patch.object(provider, '_prose', side_effect=RuntimeError('wiki offline')), \
             patch.object(provider, '_lastfm_call', return_value=wiki):
            assert provider._album_prose({'title': 'album', 'artist': 'artist'})['descriptionSource'] == 'last.fm'
        import html
        bandcamp_url = 'https://artist.bandcamp.com/album/album'
        bandcamp_page = '<script data-tralbum="' + html.escape(json.dumps({
            'current': {'title': 'album', 'about': 'A detailed album description supplied directly by its own artist.'}
        }), quote=True) + '"></script>'
        with patch.object(provider, '_lastfm_call', side_effect=RuntimeError('lastfm offline')), \
             patch.object(provider, '_fetch_page', return_value=bandcamp_page) as page:
            result = provider._album_prose({'title': 'album', 'artist': 'artist', 'links': [
                {'url': bandcamp_url}, {'url': bandcamp_url}]})
            assert result['descriptionSource'] == 'bandcamp'
            assert page.call_count == 1
        with patch.object(provider, '_fetch_json', side_effect=[RuntimeError('article gone'), {
                'extract': 'Another linked article.', 'content_urls': {'desktop': {'page': 'https://en.wikipedia.org/wiki/Good'}}}]) as fetch_wiki:
            result = provider._prose([
                {'type': 'wikipedia', 'url': 'https://en.wikipedia.org/wiki/Bad'},
                {'type': 'wikipedia', 'url': 'https://en.wikipedia.org/wiki/Good'}])
            assert result['description'] == 'Another linked article.'
            assert fetch_wiki.call_count == 2
        with patch.object(provider, '_lastfm_call', side_effect=RuntimeError('lastfm offline')):
            retained = provider._resolve(1, True)
        assert retained['album']['description'] == 'A sourced album write-up.'
        # Real transport branch: a 503 gets one retry, a 400 does not.
        url = 'https://musicbrainz.org/ws/2/release/transport-fixture?fmt=json'
        transient = urllib.error.HTTPError(url, 503, 'busy', {'Retry-After': '2'}, None)
        with patch.object(provider, '_fetch_json_fn', None), \
             patch.object(provider, '_network_wait') as wait, \
             patch.object(albuminfo.urllib.request, 'urlopen', side_effect=[transient, io.BytesIO(b'{"id":"ok"}')]) as request:
            assert provider._fetch_json(url) == {'id': 'ok'}
            assert request.call_count == 2
            assert any(call.args[0] == 2 for call in wait.call_args_list)
        permanent = urllib.error.HTTPError(url, 400, 'bad request', {}, None)
        with patch.object(provider, '_fetch_json_fn', None), \
             patch.object(provider, '_network_wait'), \
             patch.object(albuminfo.urllib.request, 'urlopen', side_effect=permanent) as request:
            try:
                provider._fetch_json(url)
                raise AssertionError('permanent failure swallowed')
            except urllib.error.HTTPError:
                assert request.call_count == 1
        # Restore the fixture's initial downloads for the correction probes.
        provider._resolve(1, True)
        row = dict(con.execute('SELECT * FROM tracks WHERE id=1').fetchone())
        scope = store.scope_key(row)
        provider._apply_command(1, 'choose', 'release-1')
        provider._apply_command(1, 'edit', {'description': 'my correction'})
        offline = True
        state = provider._resolve(1, True)
        assert state['match']['manual'] and state['match']['id'] == 'release-1'
        assert state['album']['description'] == 'my correction'
        assert state['albumError'] == 'offline' and state['similar'], state
        cached = store.cache_get(con, scope, 'resolution')
        assert cached['expires_at'] - time.time() <= 301
        provider._apply_command(1, 'clear', None)
        assert store.user_get(con, scope, 'match')['id'] == 'release-1'
        assert provider._cached_state(1)['album']['description'] == 'my correction'
        provider._apply_command(1, 'revert', 'album')
        assert not store.user_get(con, scope, 'album')
        assert con.execute("SELECT deleted FROM music_info_user WHERE kind='album'").fetchone()[0] == 1
        offline, partial = False, True
        state = provider._resolve(1, True)
        assert state['status'] == 'ready' and 'group unavailable' in state['albumError'], state
        assert store.cache_get(con, scope, 'resolution')['expires_at'] - time.time() <= 301
        partial = False
        provider._lastfm_call = lambda *_: (_ for _ in ()).throw(RuntimeError('lastfm offline'))
        state = provider._resolve(1, True)
        assert state['albumError'] == '' and state['similarError'] == 'lastfm offline', state
        assert state['similar'], 'outage erased local recommendations'
        # Recording-level legacy choices cannot bleed into another song.
        oldkey = provider._cache_key(row)
        con.execute('''INSERT INTO web_entity_matches VALUES
          (?, 'recording','musicbrainz','old-rec','old recording',1,'ready','[]',1,1,'')''', (oldkey,))
        con.commit()
        provider._legacy(con, row, scope)
        assert store.user_get(con, 'track:' + row['path'], 'legacy_match')['recordingId'] == 'old-rec'
        assert not store.user_get(con, scope, 'legacy_match')
        # An obsolete external response cannot mutate its cache or current UI.
        provider._generation = 2
        provider._active_generation = 2
        def obsolete(*_):
            provider._generation = 3
            return {'similartracks': {'track': []}}
        provider._lastfm_call = obsolete
        before = con.execute("SELECT body_json,fetched_at FROM music_info_cache WHERE kind='similar' ORDER BY cache_key").fetchall()
        try:
            provider._resolve(1, True)
            raise AssertionError('obsolete generation accepted')
        except albuminfo.Superseded:
            pass
        after = con.execute("SELECT body_json,fetched_at FROM music_info_cache WHERE kind='similar' ORDER BY cache_key").fetchall()
        assert [tuple(r) for r in before] == [tuple(r) for r in after]
        provider._deliver(2, {'trackId': 99})
        assert provider.state['trackId'] != 99
        provider._active_generation = None
        assert provider.edit(2, "album", {"description": "saved on close"})
        provider.close()
        assert store.user_get(con, scope, "album")["description"] == "saved on close"
        assert not provider.refresh(2), "closed worker accepted another request"
        entered, release = threading.Event(), threading.Event()
        def slow_fetch(url):
            entered.set()
            assert release.wait(2), "fixture fetch was never released"
            return fetch(url)
        live_worker = main.NowPlayingMetadata(None, fetch_json=slow_fetch, lastfm_call=similar)
        live_worker.refresh(1)
        assert entered.wait(2), "worker never entered fixture fetch"
        live_worker.edit(1, "album", {"description": "queued during download"})
        started = time.monotonic()
        live_worker.close()
        assert time.monotonic() - started < .5, "shutdown waited on network"
        assert store.user_get(con, scope, "album")["description"] == "queued during download"
        release.set()
        live_worker._worker.join(2)
        assert not live_worker._worker.is_alive()
        con.close()
        # Retain the pre-existing upgrade regression for early cache schemas.
        main.DATA = Path(td) / 'old-data'
        main.DB_PATH = main.DATA / 'library.db'
        main.DATA.mkdir()
        with sqlite3.connect(main.DB_PATH) as old:
            old.execute("""CREATE TABLE web_metadata (
              cache_key TEXT, kind TEXT, source TEXT, body_json TEXT,
              fetched_at REAL, expires_at REAL, error TEXT,
              PRIMARY KEY(cache_key,kind,source))""")
            for stamp, source in ((1, 'old'), (2, 'new')):
                old.execute('INSERT INTO web_metadata VALUES (?,?,?,?,?,?,?)',
                            ('album:key', 'album', source, json.dumps({'title': source}), stamp, 3, None))
        upgraded = main.open_db()
        pk = [r['name'] for r in upgraded.execute('PRAGMA table_info(web_metadata)') if r['pk']]
        assert pk == ['cache_key', 'kind']
        assert upgraded.execute('SELECT source FROM web_metadata').fetchone()[0] == 'new'
        upgraded.close()
    print('now-info-test: ok')


if __name__ == '__main__':
    run()
