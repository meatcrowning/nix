#!/usr/bin/env python3
"""Run offscreen with session-guard; no real workers or desktop actions."""
import json
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
    window.widgets['training_unit'].setCurrentText('epochs')
    window.widgets['epochs'].setValue(7)
    assert not window.widgets['steps'].isEnabled()
    assert window.widgets['epochs'].isEnabled()
    settings = window.collect()
    assert settings.training_unit == 'epochs' and settings.epochs == 7
    assert settings.sample_every == 17 and settings.sample_unit == 'epochs'
    assert settings.sample_count == 3
    window.handle_event({'event': 'progress', 'step': 43, 'total': 80, 'epoch': 2.15, 'current_epoch': 3, 'total_epochs': 4, 'epoch_step': 3, 'steps_per_epoch': 20})
    assert window.progress.value() == 43 and window.progress.maximum() == 80
    assert 'epoch 3 / 4' in window.progress.format()
    assert 'step 43 / 80' in window.progress.format()
    assert '3 / 20' in window.progress.toolTip()
    window.handle_event({'event': 'error', 'message': 'synthetic failure'})
    assert window.status.text() == 'synthetic failure'
    window.widgets['sample_seed_mode'].setCurrentIndex(1)
    window.widgets['sample_seeds'].setText('11, 22, 33')
    window.widgets['sample_baseline'].setChecked(True)
    preset = Path(tmp) / 'custom-preset.json'
    window.preset_file(preset, True)
    window.widgets['sample_count'].setValue(1)
    window.preset_file(preset, False)
    assert window.collect().sample_count == 3 and window.collect().sample_baseline
    window.persist_settings()
    assert json.loads(main.CONFIG.read_text())['epochs'] == 7
    # No QProcess: prove live controls only send the sampling mailbox message.
    from types import SimpleNamespace
    sent = []
    window.proc = SimpleNamespace(write=lambda value: sent.append(json.loads(value)))
    window.active = lambda: True
    window.mode = 'training'
    window.handle_event({'event': 'capabilities', 'live_sampling': True})
    assert window.widgets['sample_prompt'].isEnabled()
    assert window.widgets['sample_every'].isEnabled()
    assert not window.widgets['sample_width'].isEnabled()
    window.widgets['sample_enabled'].setChecked(False)
    assert sent[-1]['sampling']['sample_enabled'] is False
    window.widgets['sample_every'].setValue(0)
    window.update_buttons()
    assert window.apply_samples.isEnabled()
    window.widgets['sample_every'].setValue(17)
    window.widgets['sample_enabled'].setChecked(True)
    assert sent[-1]['sampling']['sample_enabled'] is True
    window.handle_event({'event': 'sampling_update', 'request_id': window.sampling_request_id,
                         'applied': True, 'enabled': True})
    assert window.sampling_status.text().startswith('Applied:')
    window.active = lambda: False
    window.proc = None
    window.close()
    window2 = main.Window()
    assert window2.collect().sample_seed_mode == 'random'
    assert window2.collect().sample_seeds == '11, 22, 33'
    assert window2.collect().sample_count == 3
    assert window2.collect().sample_unit == 'epochs'
    assert window2.collect().training_unit == 'epochs'
    assert window2.collect().epochs == 7
    window2.close()
    print('Offscreen controls, progress and persistence OK')
