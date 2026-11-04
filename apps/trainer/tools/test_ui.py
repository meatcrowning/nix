#!/usr/bin/env python3
"""Run offscreen with session-guard; no real workers or desktop actions."""
import os
from pathlib import Path
import sys
import tempfile

assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from PySide6.QtWidgets import QApplication

with tempfile.TemporaryDirectory() as tmp:
    main.CONFIG = Path(tmp) / 'config/settings.json'
    main.ENGINE = Path(tmp) / 'engine'
    main.ENGINE.mkdir()
    (main.ENGINE / 'revision').touch()
    app = QApplication([])
    assert app.platformName() == 'offscreen'
    window = main.Window()
    calls = []
    window.launch = lambda *args: calls.append(args)
    window.setup()
    assert calls[-1][-1] == 'setup'
    window.widgets['sample_every'].setValue(17)
    window.widgets['sample_unit'].setCurrentText('epochs')
    window.widgets['sample_count'].setValue(3)
    settings = window.collect()
    assert settings.sample_every == 17 and settings.sample_unit == 'epochs'
    assert settings.sample_count == 3
    window.handle_event({'event': 'progress', 'step': 43, 'total': 80, 'epoch': 2.1})
    assert window.progress.value() == 43 and window.progress.maximum() == 80
    window.handle_event({'event': 'error', 'message': 'synthetic failure'})
    assert window.status.text() == 'synthetic failure'
    window.close()
    window2 = main.Window()
    assert window2.collect().sample_count == 3
    assert window2.collect().sample_unit == 'epochs'
    window2.close()
    print('Offscreen controls, progress and persistence OK')
