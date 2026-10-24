#!/usr/bin/env python3
"""WiZ command checks using fake lamps and a temporary home; no network or GUI."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile

spec = importlib.util.spec_from_file_location('wizlights', Path(__file__).resolve().parents[1] / 'lib/unity-quantal/wizlights.py')
wiz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wiz)

with tempfile.TemporaryDirectory() as directory:
    os.environ['HOME'] = directory
    root = Path(directory)
    tray = root / '.local/bin/wizlight-tray.py'
    tray.parent.mkdir(parents=True)
    tray.write_text("raise RuntimeError('must never execute')\nLIGHTS = [{'name': 'One', 'ip': 'one'}, {'name': 'Two', 'ip': 'two'}]\n")
    wiz.SETTINGS = str(root / 'config/settings.json')
    report = str(root / 'report.json')
    states = {'one': {'state': True, 'dimming': 95, 'r': 12, 'g': 34, 'b': 56},
              'two': {'state': False, 'dimming': 10}}
    calls = []
    offline = set()

    def call(ip, method, params):
        calls.append((ip, method, params))
        if ip in offline:
            return None
        if method == 'getPilot':
            return dict(states[ip])
        states[ip].update(params)
        return {'success': True}

    wiz.call = call
    wiz.fetch(report, {})
    assert all(method == 'getPilot' for _, method, _ in calls), 'polling changed a lamp'
    wiz.fetch(report, {'target': 'all', 'action': 'toggle'})
    assert not any(s['state'] for s in states.values())
    wiz.fetch(report, {'target': 'all', 'action': 'toggle'})
    assert all(s['state'] for s in states.values())
    wiz.fetch(report, {'target': 'one', 'action': 'brightness', 'value': 20})
    assert states['one']['dimming'] == 100 and states['two']['dimming'] == 10
    wiz.fetch(report, {'target': 'two', 'action': 'brightness', 'value': -5})
    assert states['two']['dimming'] == 10
    wiz.fetch(report, {'target': 'all', 'action': 'color', 'value': [3, 4, 5]})
    assert all([s[k] for k in ('r', 'g', 'b')] == [3, 4, 5] for s in states.values())
    wiz.fetch(report, {'target': 'one', 'action': 'toggle'})
    wiz.fetch(report, {'target': 'one', 'action': 'color', 'value': [9, 8, 7]})
    assert not states['one']['state']
    wiz.fetch(report, {})
    wiz.fetch(report, {'target': 'one', 'action': 'toggle'})
    assert [states['one'][k] for k in ('r', 'g', 'b')] == [9, 8, 7]
    offline.add('two')
    wiz.fetch(report, {'target': 'two', 'action': 'toggle'})
    data = json.loads(Path(report).read_text())
    assert data['error'] and not data['lights'][1]['online']
    assert states['two']['state'], 'offline control changed state'
    assert json.loads(Path(wiz.SETTINGS).read_text())['lights']['one']['rgb'] == [9, 8, 7]
print('PASS: WiZ poll, group and individual controls, limits, color persistence, offline handling')
