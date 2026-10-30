#!/usr/bin/env python3
"""Offscreen remote gallery fixture; no real network, mounts, models, or GPU."""
import base64
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(APP), str(APP.parent / 'pylib')]


def main():
    if os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
        raise SystemExit('Run under the offscreen session guard')
    with tempfile.TemporaryDirectory(prefix='painter-catalogue-gallery-') as work:
        root = Path(work)
        os.environ.update(PAINTER_CATALOGUE='1', PAINTER_OUT=str(root / 'local'),
                          PAINTER_PEER_OUT=str(root / 'unmounted'), XDG_CACHE_HOME=str(root / 'cache'),
                          XDG_STATE_HOME=str(root / 'state'), PAINTER_MODELS=str(root / 'models'))
        from PySide6.QtCore import QCoreApplication
        from PIL import Image
        import io
        import catalogue as C
        import gallery as G
        import registry as R
        app = QCoreApplication([])
        buffer = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(buffer, 'JPEG')
        remote = dict(version=1, revision='one', outputs=[
            dict(relative='first.png', mtime=1, size=10, stamp='1000000000-10', params={'positive': 'red cube'}),
            dict(relative='video/clip.mp4', mtime=2, size=20, stamp='2000000000-20', params={'positive': 'blue sphere'})])
        def fetch(route, query=None, limit=None):
            import json
            if route == 'thumbnail':
                return buffer.getvalue()
            if route == 'models':
                return json.dumps(dict(version=1, revision='models', models=[
                    dict(relative='diffusion_models/base.safetensors', role='diffusion', keys=['weight'], dims={})])).encode()
            return json.dumps(remote).encode()
        with patch.object(C, '_get', fetch):
            registry = R.Registry()
            assert registry.base_models()[0].keys == {'weight'}
            gallery = G.Gallery()
            gallery.load_background()
            until = time.monotonic() + 5
            while gallery._history_job is not None and time.monotonic() < until:
                app.processEvents()
                time.sleep(.005)
            assert gallery.rowCount() == 2
            assert gallery.paramsAt(1)['positive'] == 'red cube'
            gallery.setFilter('blue sphere')
            assert gallery.rowCount() == 1
            gallery.setFilter('')
            for row in gallery._all:
                if row['is_video']:
                    gallery.requestPoster(row['path'])
                else:
                    gallery.requestThumb(row['path'])
            until = time.monotonic() + 5
            while gallery._thumb_busy and time.monotonic() < until:
                app.processEvents()
                time.sleep(.005)
            assert all(row['poster'] if row['is_video'] else row['thumb'] for row in gallery._all)
            assert not (root / 'unmounted').exists()
        print('catalogue gallery: discovery, model keys, filter, params, still/video thumbnails without a mount passed')


if __name__ == '__main__':
    main()
