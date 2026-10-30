#!/usr/bin/env python3
"""Controller/socket/GTK integration fixture; run only through unity-test.sh."""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

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
assert "layout_qt" not in sys.modules, "GTK startup imported the Quick layout editor"
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
assert engine.snapshot({})['rate'] == ctl.rate
saved_rows = ctl.gallery._rows
thumb_requests, poster_requests = [], []
thumb_method, poster_method = ctl.gallery.requestThumb, ctl.gallery.requestPoster
try:
    ctl.gallery._rows = [dict(path='/fake/%d.png' % n, name=str(n), is_video=False)
                         for n in range(5000)]
    ctl.gallery.requestThumb = thumb_requests.append
    ctl.gallery.requestPoster = poster_requests.append
    page = engine.snapshot(dict(offset=100, limit=10000, thumbFirst=8, thumbLast=16))
    assert len(page['gallery']) == 180 and page['total'] == 5000
    assert thumb_requests == ['/fake/%d.png' % n for n in range(108, 116)]
    assert not poster_requests
finally:
    ctl.gallery._rows = saved_rows
    ctl.gallery.requestThumb, ctl.gallery.requestPoster = thumb_method, poster_method
import spellcheck
real_checker = spellcheck._ENGINE
class FixtureSpelling:
    available = True
    def check(self, word): return word != 'helo'
    def suggest(self, word): return ['hello']
    def learn(self, word): self.learned = word
spellcheck._ENGINE = FixtureSpelling()
spelling = engine.dispatch(dict(op='spell', field=7, text='é helo world'))
assert spelling['words'] == [dict(start=2, end=6, word='helo', suggestions=['hello'])]
assert spelling['field'] == 7
engine.dispatch(dict(op='spell_learn', word='helo'))
assert spellcheck._ENGINE.learned == 'helo'
spellcheck._ENGINE = real_checker

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
import wildcards as W
original_options = ctl.wildcardOptions
engine.dispatch(dict(op='wildcard_line', name='pose', index=0, enabled=False))
assert not W.load_options(P.STATE / 'wildcards.json')['pose'][0]['enabled']
saved_options = ctl.wildcardOptions
params['wildcard_options'] = saved_options
Path('/home/test/out/fixture.png').write_bytes(P.pngmeta.upsert_text(
    Path('/home/test/out/fixture.png').read_bytes(), {'painter': json.dumps(params)}))
ctl.restoreWildcardOptions(original_options)
engine.dispatch(dict(op='restore', path='/home/test/out/fixture.png'))
assert ctl.wildcardOptions == saved_options
ctl.restoreWildcardOptions(original_options)


before_compare = json.dumps(engine.settings, sort_keys=True)
compare = engine.dispatch(dict(op='compare_params', path='/home/test/out/fixture.png'))
assert compare['snapshot']['settings']['positive'] == 'restored prompt'
assert json.dumps(engine.settings, sort_keys=True) == before_compare
assert engine.model == params['model']
from parameter_compare import snapshot
assert snapshot(dict(seed=2**64-1), ctl)['settings']['seed'] == 2**64-1
assert snapshot({}, ctl) is None
assert snapshot(dict(width=1024, height=1024, aspectW=7, aspectH=7, megapixels=1.05), ctl)['settings']['aspectW'] == 7
stop_calls = []
real_soft, real_hard = ctl.stopAndSave, ctl.cancel
ctl.stopAndSave = lambda: stop_calls.append('decode')
ctl.cancel = lambda: stop_calls.append('hard')
engine.dispatch(dict(op='cancel'))
engine.dispatch(dict(op='hard_stop'))
assert stop_calls == ['decode', 'hard']
ctl.stopAndSave, ctl.cancel = real_soft, real_hard

# Layout state survives settings persistence and is cleared by an older output.
import moss_layout
layout_editor = moss_layout.Editor(moss_layout.fresh(640, 768, 'A poster'))
layout_editor.add('object')['caption'] = 'A red cup'
layout_editor.doc['enabled'] = True
engine.dispatch(dict(op='settings', model=engine.model, settings={'moss_layout': layout_editor.doc}))
assert E.userprefs.saved_for(engine.model)['moss_layout'] == layout_editor.doc
original = Path('/home/test/out/fixture.png').read_bytes()
Path('/home/test/out/fixture.png').write_bytes(P.pngmeta.upsert_text(original, {
    'painter': json.dumps(dict(params, moss_layout=layout_editor.doc, width=1280, height=720))}))
engine.dispatch(dict(op='restore', path='/home/test/out/fixture.png'))
assert engine.settings['moss_layout'] == layout_editor.doc
assert engine.settings['megapixels'] == .9216
Path('/home/test/out/fixture.png').write_bytes(original)
engine.dispatch(dict(op='restore', path='/home/test/out/fixture.png'))
assert engine.settings['moss_layout'] == {}

# Legacy bbox metadata and freshly pasted drafts share the same editor state.
layout_editor.doc['enabled'] = True
raw = moss_layout.compile(layout_editor.doc)
Path('/home/test/out/fixture.png').write_bytes(P.pngmeta.upsert_text(original, {
    'painter': json.dumps(dict(params, positive=raw, width=640, height=768))}))
engine.dispatch(dict(op='restore', path='/home/test/out/fixture.png'))
assert engine.settings['positive'] == 'A poster'
assert engine.settings['moss_layout']['items'][0]['box'] == layout_editor.doc['items'][0]['box']
Path('/home/test/out/fixture.png').write_bytes(original)
engine.dispatch(dict(op='restore', path='/home/test/out/fixture.png'))
# Gate the input path as MOSS without loading or submitting a model.
original_family = ctl._selected_family
ctl._selected_family = lambda: dict(id='moss_image')
try:
    engine.dispatch(dict(op='settings', model=engine.model, settings=dict(positive=raw)))
    assert engine.settings['positive'] == 'A poster'
    assert engine.settings['moss_layout']['enabled']
finally:
    ctl._selected_family = original_family
engine.dispatch(dict(op='restore', path='/home/test/out/fixture.png'))

# Different pipelines must not inherit controls their graphs ignore.
from types import SimpleNamespace
for edit, video in [(False, False), (True, False), (False, True)]:
    flags = SimpleNamespace(isEdit=edit, isVideo=video, editSampling=False,
                            editPatches=False, encoderControls=False)
    wire = E.submission(engine.settings, flags)
    assert 'moss_layout' not in wire
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
preview_tick = ctl._preview_tick
ctl._on_preview(None, bytes(buf.data()), 'png')
# Preview decoding is asynchronous and coalesced; wait for its published frame,
# not merely for the sampler signal to return.
deadline = time.monotonic() + 5
while ctl._preview_tick == preview_tick and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(.005)
assert ctl._preview_tick > preview_tick, 'preview decode did not complete'
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
watchdog = QTimer()
watchdog.setSingleShot(True)
watchdog.timeout.connect(app.quit)
watchdog.start(45000)
# The GTK tag control traverses the actual socket and asynchronous worker,
# with a tiny fake completion process and scratch model instead of inference.
fake_tags = Path('/home/test/fake-tags')
fake_tags.write_text('#!' + sys.executable + '\nimport sys\nprint("A fox rests in snow. [end of text]" if "Write a concise visual description" in sys.argv[-1] else "snow, fox, forest,", flush=True)\n')
fake_tags.chmod(0o700)
fake_model = Path('/home/test/tag-model')
fake_model.touch()
os.environ.update(PAINTER_TAG_LLAMA=str(fake_tags), PAINTER_TAG_MODEL=str(fake_model))
# Keep the isolated harness local regardless of its inherited hostname.
import tagger
tagger.worker_command = lambda: [sys.executable, str(Path(tagger.__file__).with_name('tagger_worker.py'))]
app.exec()
if child.poll() is None:
    child.kill()
    child.wait()
    raise AssertionError('GTK test timed out')
assert child.returncode == 0, child.returncode
watchdog.stop()
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
assert E.userprefs.load()['unity.historyWidth'] == 240
assert E.userprefs.load()['unity.sidebarWidth'] == 440
assert E.userprefs.load()['layout.canvasHeight'] == 380
assert E.userprefs.load()['layout.regionListHeight'] >= 80
assert E.userprefs.load()['layout.regionPromptHeight'] > 95
ctl._scan_pool.waitForDone()
ctl.gallery._thumb_pool.waitForDone()
print('PASS: GTK socket, submission, restore, persistence, stale model and pipeline contracts')

# Exercise real asynchronous page responses and cached-image decoding together.
landscape = QImage(160, 90, QImage.Format_RGB32)
landscape.fill(QColor('blue'))
history = Path('/home/test/history')
history.mkdir()
for n in range(300):
    landscape.save(str(history / ('history-%03d.png' % n)))
ctl.gallery._all = [ctl.gallery._row_for(p) for p in sorted(history.glob('*.png'))]
ctl.gallery._refilter()
child = subprocess.Popen([os.environ['PACKAGE']+'/bin/unity-quantal-runtime', '/usr/bin/python',
                          '/home/test/nix/apps/painter/tools/history-wire-test.py',
                          '/run/user/1000/engine.sock'], env=child_env)
watchdog.start(50000)
app.exec()
if child.poll() is None:
    child.kill()
    child.wait()
assert child.returncode == 0, child.returncode
ctl.gallery._thumb_pool.waitForDone()
