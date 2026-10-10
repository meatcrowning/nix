#!/usr/bin/env python3
"""Controller/socket/GTK integration fixture; run only through unity-test.sh."""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

assert os.environ['HOME'] == '/home/test'
assert os.environ['QT_QPA_PLATFORM'] == 'offscreen'
assert Path('/work/inside.sh').is_file()
# The outer namespace is the security boundary, plus explicit controller stubs.
child_env = os.environ.copy()
os.environ.pop('DISPLAY', None)
os.environ.pop('WAYLAND_DISPLAY', None)
os.environ.update(PAINTER_MODELS='/home/test/models', PAINTER_OUT='/home/test/out',
                  PAINTER_PEER_OUT='', PAINTER_SYNC_SCAN='1', DESK_SESSION='unity',
                  XDG_STATE_HOME='/home/test/state', XDG_CACHE_HOME='/home/test/cache')
sys.path.insert(0, '/source/apps/painter')
sys.path.insert(0, '/source/apps/pylib')
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QImage, QColor
import main as P
import unity_engine as E
# Entry routing must choose the GTK engine before constructing a Qt window.
os.environ['PATH'] = os.environ['PACKAGE'] + '/bin:' + os.environ['PATH']
real_run = E.run
E.run = lambda painter: 17
assert P.main() == 17
E.run = real_run

for name, key in [('alpha-model', 'double_blocks.0.img_attn.qkv.weight'),
                  ('beta-model', 'model.diffusion_model.input_blocks.0.0.weight')]:
    path = Path('/home/test/models/unet') / (name + '.safetensors')
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps({key: {'dtype': 'BF16', 'shape': [16, 16], 'data_offsets': [0, 512]}}).encode()
    path.write_bytes(struct.pack('<Q', len(data)) + data + b'\0' * 512)

P.Painter._refresh_unit = lambda self: None
P.C.ComfyClient.fetch_object_info = lambda *_: None
app = QGuiApplication([])
assert app.platformName() == 'offscreen'
ctl = P.Painter()
ctl._unit_poll.stop()
ctl._probe.stop()
ctl._scan_retry.stop()
ctl.rescan()
app.processEvents()
ctl._object_info = {}
ctl._samplers = ['euler', 'heun']
ctl._schedulers = ['normal', 'simple']
ctl._set_status('Ready (isolated fixture)')
engine = E.Engine(ctl, P.Prefs())
assert len(engine.snapshot({})['models']) == 2
json.dumps(engine.snapshot({}))  # no QObject/registry entries on the wire

image = QImage(80, 60, QImage.Format_RGB32)
image.fill(QColor('red'))
Path('/home/test/out').mkdir(exist_ok=True)
image.save('/home/test/out/fixture.png')
params = dict(model=engine.model, positive='restored prompt', negative='restored negative',
              seed=42, width=640, height=768, steps=17, cfg=3.5)
Path('/home/test/out/fixture.png').write_bytes(P.pngmeta.upsert_text(
    Path('/home/test/out/fixture.png').read_bytes(), {'painter': json.dumps(params)}))
ctl.gallery.load_existing()

# Exercise command validation and persistence without a real generation.
engine.dispatch(dict(op='settings', model=engine.model,
                     settings=dict(positive='saved prompt', steps=23, width=768, height=1024)))
assert E.userprefs.saved_for(engine.model)['steps'] == 23
assert E.userprefs.saved_for(engine.model)['aspectW'] == 3
try:
    engine.dispatch(dict(op='generate', model='wrong', settings={'positive': 'bad'}))
    raise AssertionError('stale model submitted')
except ValueError:
    pass
try:
    engine.dispatch(dict(op='settings', model=engine.model, settings={'count': -1}))
    raise AssertionError('invalid count accepted')
except ValueError:
    pass
engine.dispatch(dict(op='restore', path='/home/test/out/fixture.png'))
assert engine.settings['seed'] == 42 and not engine.settings['randomSeed']
assert engine.settings['positive'] == 'restored prompt'

# Different pipelines must not inherit controls their graphs ignore.
from types import SimpleNamespace
for edit, video in [(False, False), (True, False), (False, True)]:
    flags = SimpleNamespace(isEdit=edit, isVideo=video, editSampling=False,
                            editPatches=False, encoderControls=False)
    wire = E.submission(engine.settings, flags)
    if edit:
        assert 'cfg' not in wire and 'width' not in wire and wire['edit']
    elif video:
        assert 'cfg' not in wire and 'negative' not in wire and 'duration' in wire
    else:
        assert wire['cfg'] == 3.5 and wire['width'] == 640

submitted = []
ctl.generate = lambda params, count: submitted.append((params, count))
ctl.cancel = lambda: ctl._set_status('Cancelled fixture')
server = E.Server('/run/user/1000/engine.sock', engine, app)
child = subprocess.Popen([os.environ['PACKAGE']+'/bin/unity-quantal-runtime', '/usr/bin/python',
                          '/home/test/nix/apps/painter/tools/unity-gtk-test.py',
                          '/run/user/1000/engine.sock'], env=child_env)
timer = QTimer()
timer.setInterval(50)
timer.timeout.connect(lambda: app.quit() if child.poll() is not None else None)
timer.start()
QTimer.singleShot(45000, app.quit)
app.exec()
if child.poll() is None:
    child.kill()
    child.wait()
    raise AssertionError('GTK test timed out')
assert child.returncode == 0, child.returncode
assert submitted, 'GTK Generate did not reach controller'
assert submitted[0][0]['positive'] == 'a native GTK prompt'
assert submitted[0][0]['seed'] == 1234
assert submitted[0][1] == 2
assert E.userprefs.saved_for(engine.model)['positive'] == 'last edit before closing'
ctl._scan_pool.waitForDone()
ctl.gallery._thumb_pool.waitForDone()
print('PASS: GTK socket, submission, restore, persistence, stale model and pipeline contracts')
