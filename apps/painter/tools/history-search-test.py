#!/usr/bin/env python3
"""Synthetic search semantics and delayed metadata races; no backend or GUI."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from datetime import datetime
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(APP), str(APP.parent / 'pylib')]
import history_search as S


def semantics():
    doc = S.document('painter_42.png', dict(positive='A red bird on Straße', negative='cat blur',
        model='MOSS.safetensors', family='moss_image', seed=0,
        loras=[{'name': 'soft light.safetensors'}]), mtime=datetime(2026, 11, 4, 12).timestamp())
    for query in ('red bird', '"red bird" model:MOSS -cat', 'negative:cat',
                  'lora:"soft light" seed:0 type:image', 'STRASSE',
                  'date:2026-11-04 before:2026-11-05 after:2026-11-03',
                  '"red bird', 'prompt:"red bird" -lora:sketch', 'filename:42'):
        assert S.matches(doc, S.parse(query)), query
    for query in ('cat', '"bird red"', '-"red bird"', 'seed:42', 'type:video',
                  'before:2026-11-04', 'after:2026-11-04', 'date:2026-99-99',
                  'unknown:red', 'lora:sketch'):
        assert not S.matches(doc, S.parse(query)), query
    folded = S.document('folded.png', dict(positive='bird, (cat:-1)', negative='',
        prompt_boxes={'positive': 'bird', 'negative': 'cat'}, toggles={'negpip': True}))
    assert not S.matches(folded, S.parse('cat'))
    assert S.matches(folded, S.parse('negative:cat'))
    expanded = S.document('wildcard.png', dict(positive='blue sky', prompt_boxes={'positive': '__sky__'}))
    assert S.matches(expanded, S.parse('blue'))
    assert S.matches(S.document('broken.png', ['bad metadata']), S.parse('filename:broken'))


def asynchronous():
    if os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
        raise SystemExit('Run under the offscreen session guard')
    with tempfile.TemporaryDirectory(prefix='painter-search-') as work:
        os.environ.update(PAINTER_CATALOGUE='0', PAINTER_OUT=work, PAINTER_PEER_OUT='',
                          XDG_CACHE_HOME=work + '/cache', XDG_STATE_HOME=work + '/state')
        from PySide6.QtCore import QCoreApplication
        import gallery as G
        app = QCoreApplication([])
        class Gallery(G.Gallery):
            def _want_thumb(self, row): pass
            def _want_poster(self, path): pass
        gallery = Gallery()
        def row(name, stamp=1):
            return G._history_row(Path(work) / name, (stamp, 10))
        def pump(until):
            deadline = time.monotonic() + 5
            while not until() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.001)
            assert until(), 'search worker did not finish'
        started, release = threading.Event(), threading.Event()
        calls = []
        main_thread = threading.get_ident()
        def read(path):
            assert threading.get_ident() != main_thread, 'metadata read on UI thread'
            calls.append(path)
            started.set()
            assert release.wait(5)
            if path.endswith('broken.png'):
                raise ValueError('corrupt metadata')
            return {'positive': 'red bird', 'model': 'moss', 'loras': [{'name': 'style'}]}
        with patch.object(G.outmeta, 'params_for', read):
            old = row('old.png')
            gallery._install_history([old])
            try:
                gallery.setFilter('bird')
                assert started.wait(2)
                # GUI remains callable while metadata is blocked. Replace a row,
                # change the query, and add a live job before old results arrive.
                fresh = row('old.png', 2)
                gallery._install_history([fresh, row('broken.png')])
                gallery.setFilter('model:moss lora:style')
                gallery.begin_live('test')
                assert gallery.rowCount() == 1
                release.set()
                pump(lambda: gallery._search_job is None)
                assert 'search' not in old, 'retired row received stale result'
                assert fresh['search']['model'] == 'moss'
                assert gallery.rowCount() == 2 and gallery._rows[0].get('live')
                assert sum(p.endswith('old.png') for p in calls) == 2
                before = len(calls)
                gallery.setFilter('negative:bird')
                assert gallery.rowCount() == 1
                gallery.setFilter('')
                assert gallery.rowCount() == 3 and len(calls) == before
                gallery.setFilter('filename:broken')
                assert gallery.rowCount() == 2
                # New completed outputs participate in an active metadata filter.
                gallery.setFilter('model:moss')
                gallery.add(str(Path(work) / 'new.png'), job='other')
                pump(lambda: gallery._search_job is None)
                assert any(r['name'] == 'new.png' for r in gallery._rows)
                # Clearing a query stops subsequent batches; resuming reuses the
                # first batch and indexes the rest exactly once.
                before = len(calls)
                gallery._install_history([row('batch%d.png' % i) for i in range(70)])
                gallery.setFilter('')
                pump(lambda: gallery._search_job is None)
                assert len(calls) - before == 32
                gallery.setFilter('model:moss')
                pump(lambda: gallery._search_job is None)
                assert len(calls) - before == 70
                assert gallery.rowCount() == 71  # includes the live row
            finally:
                release.set()
                gallery._search_pool.waitForDone()
        print('PASS search syntax, negative separation, async reads, stale results, live/new rows, corrupt metadata')


if __name__ == '__main__':
    semantics()
    asynchronous()
