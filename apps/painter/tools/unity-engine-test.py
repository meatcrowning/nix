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
# An edit source and a short silent clip exercise both other viewer paths.
Path('/home/test/out/.before').mkdir(exist_ok=True)
before = QImage(80, 60, QImage.Format_RGB32)
before.fill(QColor('blue'))
before.save('/home/test/out/.before/edit.png')
Path('/home/test/out/edit.png').write_bytes(P.pngmeta.upsert_text(
    Path('/home/test/out/fixture.png').read_bytes(), {'painter': json.dumps(dict(params, edit=True))}))
Path('/home/test/out/video').mkdir(exist_ok=True)
subprocess.run([os.environ['FFMPEG'], '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'testsrc2=size=96x64:rate=12', '-t', '1',
                '-c:v', 'mpeg4', '-an', '/home/test/out/video/clip.mp4'], check=True)
ctl.gallery.load_existing()

# Exercise command validation and persistence without a real generation.
engine.dispatch(dict(op='settings', model=engine.model,
                     settings=dict(positive='saved prompt', steps=23, aspectW=3, aspectH=4, megapixels=.7)))
assert E.userprefs.saved_for(engine.model)['steps'] == 23
assert E.userprefs.saved_for(engine.model)['aspectW'] == 3
assert E.userprefs.saved_for(engine.model)['megapixels'] == .7
assert engine.settings['width'] == ctl.dims('3:4', .7, engine.multiple)['width']
engine.dispatch(dict(op='settings', heights={'positive': 210, 'negative': 95}))
assert E.userprefs.load()['prompt.posH'] == 210
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

# The existing controller's sampler path supplies transient frames over the
# private socket, with no preview files and no repeated image payload.
ctl.gallery.begin_live('fixture', grab=True)
engine.set_view('live://generating')
from PySide6.QtCore import QBuffer, QIODevice
buf = QBuffer()
buf.open(QIODevice.WriteOnly)
image.save(buf, 'PNG')
ctl._on_preview(None, bytes(buf.data()), 'png')
media = engine.snapshot({})['media']
assert media['data'] and media['path'] == 'live://generating'
assert not engine.snapshot({'frameTick': media['tick']})['media']['data']
assert any(r['live'] for r in engine.snapshot({})['gallery'])
ctl.gallery.end_live(replaced_by='/home/test/out/fixture.png')
assert engine.view_path == '/home/test/out/fixture.png'

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
expected = ctl.dims('16:9', .8, engine.multiple)
assert submitted[0][0]['width'] == expected['width']
assert submitted[0][0]['height'] == expected['height']
assert engine.player is not None
assert engine.player.audioOutput() is None
assert engine.player.source().isEmpty(), 'decoder retained after leaving clip'
assert E.userprefs.saved_for(engine.model)['positive'] == 'last edit before closing'
assert E.userprefs.load()['prompt.posH'] == 285
assert E.userprefs.load()['prompt.negH'] == 40
assert E.userprefs.load()['unity.systemH'] == 600
ctl._scan_pool.waitForDone()
ctl.gallery._thumb_pool.waitForDone()
print('PASS: GTK socket, submission, restore, persistence, stale model and pipeline contracts')
