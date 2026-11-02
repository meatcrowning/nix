#!/usr/bin/env python3
"""Isolated selection timing, stale replies, coalescing and thumbnail fallbacks."""
import importlib.util
import os
from pathlib import Path
import tempfile
import time
from threading import Event
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('ui', Path(__file__).with_name('ui-test.py'))
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QColor
import catalogue
import gallery

with tempfile.TemporaryDirectory(prefix='painter-loading-test-') as tmp:
    for key, name in [('XDG_STATE_HOME', 'state'), ('XDG_CACHE_HOME', 'cache'),
                      ('PAINTER_OUT', 'out'), ('PAINTER_PEER_OUT', 'peer')]:
        os.environ[key] = str(Path(tmp) / name)
    os.environ['KDESHELL_STATE'] = str(Path(tmp) / 'shell.ini')
    os.environ['PAINTER_MODELS'] = u.fake_models(str(Path(tmp) / 'models'))
    app, engine, win, ctl, keep = u.build(tmp)
    path = str(Path(tmp) / 'out' / 'fixture.png')
    Path(path).parent.mkdir(exist_ok=True)
    image = QImage(20, 10, QImage.Format_RGBA8888)
    image.fill(QColor('red'))
    assert image.save(path)
    ctl.gallery.add(path)
    gate = Event()
    def resolve(p):
        assert gate.wait(5)
        return p + '.before'
    try:
        with patch.object(ctl, '_compare_source', side_effect=resolve) as reader:
            start = time.perf_counter()
            for _ in range(30):
                assert ctl.compareSource(path) == ''
            elapsed = 1000 * (time.perf_counter() - start)
            assert elapsed < 50, elapsed
            u.spin(50)
            assert reader.call_count == 1
            gate.set()
            for _ in range(100):
                u.spin(10)
                if ctl.compareSource(path): break
            assert ctl.compareSource(path) == path + '.before'
            assert reader.call_count == 1
        print('PASS comparison lookup dispatch %.2f ms for 30 requests; coalesced and cached' % elapsed)
        gate.clear()
        local = str(Path(tmp) / 'display.png')
        image.save(local)
        def display(p):
            assert gate.wait(5)
            return local
        with patch.object(catalogue, 'output', return_value=dict(relative='fixture.png', stamp='one')):
            with patch.object(catalogue, 'display_image', side_effect=display) as fetch:
                start = time.perf_counter()
                ctl.outputSource(path)
                assert 1000*(time.perf_counter()-start) < 50
                assert ctl.outputPending(path)
                for _ in range(30): ctl.outputSource(path)
                u.spin(50)
                assert fetch.call_count == 1
                gate.set()
                for _ in range(100):
                    u.spin(10)
                    if not ctl.outputPending(path): break
                assert ctl.outputSource(path) == QUrl.fromLocalFile(local).toString()
                assert fetch.call_count == 1
            ctl._output_cache.clear()
            with patch.object(catalogue, 'display_image', side_effect=OSError('old backend')):
                ctl.outputSource(path)
                for _ in range(100):
                    u.spin(10)
                    if not ctl.outputPending(path): break
                assert ctl.outputSource(path) == QUrl.fromLocalFile(path).toString()
        print('PASS asynchronous lossless display selection, cached revisit and older-backend fallback')
        # A tile surviving a dropped initial request must recover without a
        # model reset or scrolling it out of and back into the viewport.
        dropped = str(Path(tmp) / 'out' / 'dropped.png')
        image.save(dropped)
        with patch.object(ctl.gallery, '_want_thumb') as request:
            ctl.gallery.add(dropped)
            u.spin(150)
            assert request.called
            row = next(r for r in ctl.gallery._all if r['path'] == dropped)
            assert not row['thumb']
        for _ in range(250):
            u.spin(10)
            if row['thumb']: break
        assert row['thumb'], 'visible dropped thumbnail stayed blank'
        print('PASS surviving visible tile retries a dropped request without a model reset')
        # A failed catalogue thumbnail must still decode the mounted source.
        dest = Path(tmp) / 'fallback.jpg'
        with patch.object(catalogue, 'enabled', return_value=True), \
             patch.object(catalogue, 'output', return_value={}), \
             patch.object(catalogue, 'thumbnail', side_effect=OSError('stale stamp')):
            job = gallery._ThumbJob(path, dest)
            job.run()
        assert not QImage(str(dest)).isNull()
        print('PASS failed remote thumbnail falls back to readable source')
    finally:
        gate.set()
        ctl._compare_work.pool.waitForDone()
        ctl._output_work.pool.waitForDone()
        ctl.inspection.close()
    assert not u.WARNINGS, u.WARNINGS
