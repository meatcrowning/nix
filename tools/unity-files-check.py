#!/usr/bin/env python3
"""Exercise phone browsing with a fake KDE Connect service and mount."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('file_actions',
    Path(__file__).resolve().parents[1] / 'lib/unity-quantal/file-actions.py')
actions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(actions)

with tempfile.TemporaryDirectory(prefix='unity-phone-test-') as temporary:
    mounted = Path(temporary) / 'Phone storage'
    mounted.mkdir()
    calls = []
    available = 'test-device Galaxy Test Phone\n'

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=available)

    def call(method):
        return {'mountAndWait': True, 'mountPoint': str(mounted)}[method]

    actions.browse_phone({'kdeconnect': '/fake/kdeconnect'}, run, call)
    assert calls[-1][1:] == ['/usr/bin/nautilus', '--no-default-window', mounted.as_uri()]
    for devices in ['', available + 'other-device Galaxy Other Phone\n']:
        available = devices
        calls.clear()
        try:
            actions.browse_phone({'kdeconnect': '/fake/kdeconnect'}, run, call)
        except ValueError:
            pass
        else:
            raise AssertionError('unavailable/ambiguous phone accepted')
        assert len(calls) == 1
    available = 'test-device Galaxy Test Phone\n'
    calls.clear()
    try:
        actions.browse_phone({'kdeconnect': '/fake/kdeconnect'}, run,
                            lambda method: False if method == 'mountAndWait' else 'disabled')
    except ValueError as error:
        assert 'disabled' in str(error)
    else:
        raise AssertionError('failed mount accepted')
    assert len(calls) == 1
print('PASS: phone mount opens Files; unavailable, ambiguous and failed mounts do not launch it')
