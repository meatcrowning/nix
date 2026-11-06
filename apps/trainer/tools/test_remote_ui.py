#!/usr/bin/env python3
"""Offscreen client tests with an in-memory transport; never contacts top."""
import os
from pathlib import Path
import sys
import tempfile
import time
from dataclasses import asdict
assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
import remote
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QCloseEvent

class Fake:
    host = 'top'
    def __init__(self):
        self.calls = []
    def call(self, action, **values):
        self.calls.append((action, values))
        if action == 'inspect':
            return dict(run='/synthetic/run', settings=asdict(main.Settings()), latest={'lora':'/synthetic/run/a.safetensors'})
        if action == 'status':
            return status
        return True
    def samples(self, run):
        return Path(tmp) / 'samples'

with tempfile.TemporaryDirectory() as tmp:
    main.CONFIG = Path(tmp) / 'settings.json'
    app = QApplication([])
    assert app.platformName() == 'offscreen'
    fake = Fake()
    window = remote.Window(fake)
    window.poll_timer.stop()
    status = dict(active=True, engine=True, mode='training', state='training', started=time.time(),
                  run='/synthetic/run', generation='a'*32, sequence=1, lines=[(1, 'hello')],
                  events=[dict(event='capabilities', live_sampling=True, sample_now=True)])
    window.status_result(status)
    # Queue a control while a metadata request is in flight; it must not vanish.
    window.command('pause')
    for _ in range(100):
        window.tick()
        if any(action == 'control' for action, _ in fake.calls) and window.pending is None:
            break
        time.sleep(.005)
    assert any(action == 'control' and args['message']['command'] == 'pause' for action, args in fake.calls)
    assert window.sample_now.isEnabled()
    window.apply_sampling(force=True)
    for _ in range(100):
        window.tick()
        if window.pending is None:
            break
        time.sleep(.005)
    assert any(action == 'control' and args['message'].get('sampling', {}).get('force') for action, args in fake.calls)
    # Disconnect disables controls, never writes stop. Reconnecting re-enables.
    window.connected = False
    window.update_buttons()
    assert not window.stop.isEnabled()
    window.status_result(status)
    assert window.stop.isEnabled()
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()
    assert not any(action == 'control' and args['message']['command'] == 'stop' for action, args in fake.calls)
    window.persist_timer.stop()
    window.timer.stop()
print('Remote reconnect, queued controls, sampling and detach OK')
