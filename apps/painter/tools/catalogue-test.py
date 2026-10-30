#!/usr/bin/env python3
"""Synthetic catalogue protocol, cache, compatibility, and traversal checks."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(APP), str(APP.parent / 'pylib')]
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')


def main():
    with tempfile.TemporaryDirectory(prefix='painter-catalogue-') as temp:
        root = Path(temp)
        os.environ.update(XDG_CACHE_HOME=str(root / 'cache'), XDG_STATE_HOME=str(root / 'state'))
        import catalogue as C
        from catalogue_index import CatalogueIndex
        import registry as R
        from pngmeta import upsert_text
        models, outputs = root / 'models', root / 'outputs'
        outputs.mkdir()
        model = models / 'diffusion_models' / 'fixture.safetensors'
        model.parent.mkdir(parents=True)
        body = json.dumps({'weight': {'shape': [1], 'dtype': 'F32', 'data_offsets': [0, 4]}}).encode()
        model.write_bytes(struct.pack('<Q', len(body)) + body + bytes(4))
        target = outputs / 'first.png'
        target.write_bytes(upsert_text(PNG, {'painter': json.dumps({'positive': 'red cube'})}))
        idx = CatalogueIndex(models, outputs, root / 'server-cache')
        doc = idx.models()
        assert len(doc['models']) == 1 and 'path' not in doc['models'][0]
        assert idx.models(doc['revision'])['unchanged']
        first = idx.outputs()
        assert first['outputs'][0]['params']['positive'] == 'red cube'
        assert idx.outputs(first['revision'])['unchanged']
        (outputs / 'second.png').write_bytes(PNG)
        idx._output_time = -float('inf')
        delta = idx.outputs(first['revision'])
        assert delta['delta'] and len(delta['outputs']) == 1
        assert delta['outputs'][0]['relative'] == 'second.png'
        target.unlink()
        previous = idx.outputs()
        idx._output_time = -float('inf')
        removed = idx.outputs(previous['revision'])
        assert removed['removed'] == ['first.png']
        for value in ('../escape.png', '/etc/passwd', 'video/../../escape', '..\\escape'):
            try:
                idx.thumbnail(value, '')
            except ValueError:
                pass
            else:
                raise AssertionError('unsafe path accepted')
        row = idx.outputs()['outputs'][0]
        assert idx.thumbnail(row['relative'], row['stamp']).read_bytes().startswith(b'\xff\xd8')
        def get(route, query=None, limit=None):
            result = idx.models((query or {}).get('since', '')) if route == 'models' else idx.outputs((query or {}).get('since', ''))
            return json.dumps(result).encode()
        with patch.object(C, '_get', get):
            results = C.models(root / 'unmounted-models')
            assert len(results) == 1 and results[0]['path'].startswith(str(root / 'unmounted-models'))
            result = C.outputs(root / 'unmounted-outputs')
            assert len(result) == 1
            assert C.output(result[0]['path'])['relative'] == 'second.png'
            assert C.outputs(root / 'unmounted-outputs') == result
        with patch.object(C, '_get', side_effect=OSError('offline')):
            assert C.models(root / 'unmounted-models') == results
            assert C.outputs(root / 'unmounted-outputs') == result
        entry = R.Entry(dict(path='base.safetensors', keys=['a.weight'], dims={}))
        lora = R.Entry(dict(path='lora.safetensors', targets=['a'], kohya=True, patches_clip=True))
        assert entry.keys == {'a.weight'} and lora.targets == {'a'} and lora.kohya and lora.patches_clip
        # Import the actual route module with inert server/folder adapters.
        import asyncio
        import types
        routes = {}
        class Routes:
            def get(self, path):
                def register(fn):
                    routes[path] = fn
                    return fn
                return register
        server = types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace(routes=Routes())))
        folder = types.SimpleNamespace(get_output_directory=lambda: str(outputs))
        http = types.SimpleNamespace(web=types.SimpleNamespace(json_response=lambda doc: doc))
        with patch.dict(sys.modules, server=server, folder_paths=folder, aiohttp=http):
            spec = importlib.util.spec_from_file_location('catalogue_route_fixture', APP / 'comfy_nodes/painter_catalogue.py')
            node = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(node)
            node._index = idx
            reply = asyncio.run(routes['/painter/catalogue/outputs'](types.SimpleNamespace(query={})))
            assert reply['version'] == 1
            reply = asyncio.run(routes['/painter/catalogue/models'](types.SimpleNamespace(query={})))
            assert reply['models']
        print('catalogue: routes, revision/delta/delete, offline cache, remote metadata, header facts, thumbnail, traversal passed')


if __name__ == '__main__':
    main()
