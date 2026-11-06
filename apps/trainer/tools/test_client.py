#!/usr/bin/env python3
"""Transport fixtures: failed uploads never submit or reuse a running dataset."""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from remote import Client
from core import Settings

with tempfile.TemporaryDirectory() as tmp:
    client = Client('top')
    client.cache = Path(tmp) / 'cache'
    client.uploads = client.cache / 'uploads.json'
    dataset = Path(tmp) / 'dataset with spaces'
    dataset.mkdir()
    (dataset / 'image.Png').write_bytes(b'fixture')
    settings = asdict(Settings(dataset=str(dataset)))
    calls = []
    def call(action, **values):
        calls.append((action, values))
        return '/synthetic/uploads/' + values['token'] + '/dataset' if action == 'upload' else {'run':'/synthetic/run'}
    client.call = call
    with patch('remote.subprocess.run', return_value=SimpleNamespace(returncode=1, stderr='interrupted')):
        try:
            client.start(settings, True, uuid.uuid4().hex)
            raise AssertionError('failed upload accepted')
        except RuntimeError:
            pass
    assert not any(action == 'start' for action, _ in calls)
    token = calls[0][1]['token']
    with patch('remote.subprocess.run', return_value=SimpleNamespace(returncode=0, stderr='')) as transfer:
        client.start(settings, True, uuid.uuid4().hex)
        assert calls[1][1]['token'] == token
        assert calls[-1][0] == 'start'
        assert calls[-1][1]['settings']['dataset'].endswith(token + '/dataset')
        assert '--include=*.[pP][nN][gG]' in transfer.call_args.args[0]
        assert not json.loads(client.uploads.read_text())
        client.start(settings, True, uuid.uuid4().hex)
        assert calls[-2][1]['token'] != token
    assert settings['dataset'] == str(dataset)
print('Failed upload isolation, retry, mixed-case images and sealed dataset reuse OK')
