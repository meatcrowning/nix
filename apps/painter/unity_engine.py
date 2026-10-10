"""Painter's windowless controller adapter for the historical GTK frontend.

One private Unix socket and controller per window. Only JSON crosses the
process boundary; Quantal never imports modern Python or Qt libraries.
"""
import base64
import collections
import copy
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile

from PySide6.QtCore import QTimer, QBuffer, QIODevice, QUrl, Qt
from PySide6.QtGui import QGuiApplication, QImage

import userprefs
from unityipc import Server


FLAGS = ('isVideo', 'isEdit', 'editSampling', 'editPatches', 'supportsPatches',
         'supportsLoras', 'encoderControls', 'referenceImages', 'optionalEditImage',
         'fixedSampling', 'nativeScheduler')
HEIGHT_KEYS = {'positive': 'prompt.posH', 'negative': 'prompt.negH', 'system_prompt': 'unity.systemH'}
BASE = dict(positive='', negative='', aspectW=1, aspectH=1, width=1024, height=1024, steps=20, cfg=7.0,
            denoise=1.0, sampler_name='euler', scheduler='normal', seed=-1,
            randomSeed=True, reuseSeed=False, count=1, batch_size=1,
            duration=5.0, fps=24.0, megapixels=1.0, still=False,
            editNoScale=True, editMegapixels=1.0, useInputImage=False,
            useLastFrame=False, negpip=False, modelSampling=False,
            ms=dict(shift_start=3.5, shift_end=1.2, start_percent=0.0, end_percent=.5,
                    curve='ease_in', outside_window='hold', multiplier=1.0),
            system_prompt='', krea_sampling='native', krea_shift=1.0,
            reference_megapixels=1.0, useReferences=False)


def submission(g, ctl):
    """The three graph contracts, matching Root.qml's submit()."""
    keys = ['positive', 'seed', 'randomSeed', 'reuseSeed']
    if ctl.isEdit:
        keys += ['editNoScale', 'editMegapixels']
        if ctl.editSampling:
            keys += ['negative', 'steps', 'cfg', 'sampler_name', 'scheduler', 'denoise']
    else:
        keys += ['steps', 'denoise', 'sampler_name', 'scheduler', 'width', 'height']
        if ctl.isVideo:
            keys += ['megapixels', 'still']
            if not g['still']:
                keys += ['duration', 'fps']
        else:
            keys += ['negative', 'cfg', 'batch_size']
            if ctl.encoderControls:
                keys += ['system_prompt', 'krea_sampling', 'krea_shift', 'reference_megapixels']
    p = {key: g[key] for key in keys}
    if ctl.isEdit:
        p['edit'] = True
    elif ctl.isVideo and not g['still']:
        p.update(use_input_image=g['useInputImage'], use_last_frame=g['useLastFrame'])
    elif ctl.encoderControls:
        p['use_reference_images'] = g['useReferences']
    if (ctl.isEdit and ctl.editPatches) or (not ctl.isEdit and not ctl.isVideo):
        p['toggles'] = dict(negpip=g['negpip'], model_sampling=g['modelSampling'])
        p['model_sampling'] = copy.deepcopy(g['ms'])
    return p


class Engine:
    def __init__(self, ctl, prefs, desktop_env=None):
        self.ctl, self.prefs = ctl, prefs
        self.desktop_env = desktop_env
        self.settings = copy.deepcopy(BASE)
        self.model = ''
        self.multiple = 64
        self.messages = collections.deque(maxlen=30)
        self.revision = 0
        self._restored = False
        self.heights = {key: max(40, min(600, int(prefs.get(pref) or default)))
                       for (key, pref), default in zip(HEIGHT_KEYS.items(), (130, 64, 90))}
        self.view_path = ''
        self.before = ''
        self.player = self.sink = None
        self.frame = QImage()
        self.frame_tick = 0
        self.replacement = ''
        from types import SimpleNamespace
        ctl.preview = SimpleNamespace(image=QImage())
        ctl.gallery.liveReplaced.connect(self.live_replaced)
        ctl.toast.connect(lambda text, error: self.messages.append(dict(text=text, error=error)))
        ctl.modelChanged.connect(self.model_changed)
        ctl.selectModelByName(prefs.get('model') or '')
        ctl.restoreMode(prefs.get('mode') or '')
        ctl.restoreLastSeed(prefs.get('lastSeed') if prefs.get('lastSeed') is not None else -1)
        for key, method in [('inputImage', ctl.restoreInputImage), ('lastImage', ctl.restoreLastImage)]:
            if prefs.get(key):
                method(prefs.get(key))
        self.model_changed()

    def model_changed(self):
        c = self.ctl
        if not c.selectedName or c.selectedName == self.model:
            return
        self.model = c.selectedName
        d = c.modelDefaults()
        g = copy.deepcopy(BASE)
        g.update({k: v for k, v in d.items() if k in g})
        dims = c.dims(d.get('aspect', '1:1'), d.get('megapixels', 1), d.get('multiple', 64))
        g.update(dims)
        g['aspectW'], g['aspectH'] = map(int, d.get('aspect', '1:1').split(':'))
        g['ms'].update(d.get('model_sampling') or {})
        toggles = d.get('toggles') or {}
        g['negpip'] = bool(toggles.get('negpip', False))
        g['modelSampling'] = bool(toggles.get('model_sampling', False))
        g.update(userprefs.saved_for(self.model, self.prefs._doc))
        self.settings = g
        self.resolve_dims()
        if not self._restored:
            self._restored = True
            try:
                c.restoreLoras(json.loads(self.prefs.get('loras') or '[]'))
                c.restoreEditImages(json.loads(self.prefs.get('editExtra') or '[]'))
            except (ValueError, TypeError):
                pass
        self.revision += 1

    def save(self):
        # Merge with the on-disk document: the other desktop face owns keys
        # such as window geometry that this frontend must not overwrite.
        doc = userprefs.load()
        if self.model:
            by_model = userprefs._sub(doc, 'genByModel')
            saved = copy.deepcopy(self.settings)
            by_model[self.model] = saved
            doc.update(genByModel=json.dumps(by_model), model=self.model, mode=self.ctl.mode,
                       inputImage=self.ctl.inputImage, lastImage=self.ctl.lastImage,
                       editExtra=json.dumps(self.ctl.editExtraImages), lastSeed=self.ctl.lastSeed,
                       loras=json.dumps(self.ctl.lorasSnapshot()))
        doc.update({pref: self.heights[key] for key, pref in HEIGHT_KEYS.items()})
        self.prefs._doc = doc
        # Prefs.set owns the atomic write; force one changed key without losing
        # any unrelated desktop settings.
        self.prefs._doc.pop('unityRevision', None)
        self.prefs.set('unityRevision', self.revision)

    def update(self, request):
        if 'heights' in request:
            for key, value in request['heights'].items():
                if key in HEIGHT_KEYS:
                    if not isinstance(value, int) or not 40 <= value <= 600:
                        raise ValueError('Invalid text box height')
                    self.heights[key] = value
            self.save()
        if 'settings' not in request:
            return
        if request.get('model') != self.model:
            raise ValueError('The model changed; wait for its settings before submitting.')
        values = request['settings']
        if not isinstance(values, dict):
            raise ValueError('Invalid settings')
        g = copy.deepcopy(self.settings)
        for key, value in values.items():
            if key not in BASE:
                continue
            prototype = BASE[key]
            if isinstance(prototype, bool):
                if not isinstance(value, bool):
                    raise ValueError('Invalid ' + key)
            elif isinstance(prototype, (float, int)):
                if not isinstance(value, (float, int)) or not math.isfinite(value):
                    raise ValueError('Invalid ' + key)
            elif not isinstance(value, type(prototype)):
                raise ValueError('Invalid ' + key)
            g[key] = value
        for key, low, high in [('count', 1, 100), ('batch_size', 1, 64), ('steps', 1, 1000),
                               ('aspectW', 1, 999), ('aspectH', 1, 999), ('seed', -1, 2**53)]:
            if not low <= g[key] <= high or int(g[key]) != g[key]:
                raise ValueError('Invalid ' + key)
        for key, low, high in [('cfg', 0, 100), ('denoise', 0, 1), ('duration', .1, 120),
                               ('fps', 1, 120), ('megapixels', .01, 16), ('editMegapixels', .01, 16),
                               ('reference_megapixels', .01, 16), ('krea_shift', 0, 100)]:
            if not low <= g[key] <= high:
                raise ValueError('Invalid ' + key)
        for key, value in g['ms'].items():
            if key in ('curve', 'outside_window'):
                if not isinstance(value, str):
                    raise ValueError('Invalid sampling option')
            elif not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Invalid sampling value')
        self.settings = g
        self.resolve_dims()
        self.save()

    def resolve_dims(self):
        g = self.settings
        self.multiple = self.ctl.modelDefaults().get('multiple', 64)
        g.update(self.ctl.dims('%d:%d' % (g['aspectW'], g['aspectH']), g['megapixels'], self.multiple))

    def live_replaced(self, path):
        self.replacement = path
        if self.view_path == 'live://generating':
            self.set_view(path)

    def set_view(self, path):
        if path and path != 'live://generating':
            self.output_path(path)
        if path == self.view_path:
            return
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
        self.view_path = path
        self.before = ''
        self.frame = QImage()
        self.frame_tick += 1
        row = next((r for r in self.ctl.gallery._rows if r['path'] == path), {})
        if not path or row.get('live'):
            return
        if not row.get('is_video'):
            self.before = self.ctl.compareSource(path)
            return
        if not self.player:
            from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
            self.player = QMediaPlayer()
            self.sink = QVideoSink()
            self.player.setVideoSink(self.sink)
            # No audio output is ever attached: Painter's clips are muted.
            self.player.setLoops(QMediaPlayer.Infinite)
            self.sink.videoFrameChanged.connect(self.video_frame)
            self.player.errorOccurred.connect(lambda _code, text: self.messages.append(dict(text=text, error=True)))
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def video_frame(self, frame):
        image = frame.toImage()
        if not image.isNull():
            self.frame = image
            self.frame_tick += 1

    def media(self, request):
        live = self.view_path == 'live://generating'
        tick = ('live:%s' % self.ctl.previewTick) if live else ('video:%s' % self.frame_tick)
        image = self.ctl.preview.image if live and self.ctl.previewTick else self.frame
        result = dict(path=self.view_path, tick=tick, before=self.before, data='',
                      size=[image.width(), image.height()],
                      duration=self.player.duration() if self.player and not live else 0)
        if request.get('frameTick') != tick and not image.isNull():
            if max(image.width(), image.height()) > 1280:
                image = image.scaled(1280, 1280, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            image.save(buf, 'JPEG', 85)
            result['data'] = base64.b64encode(bytes(buf.data())).decode('ascii')
        return result

    def dispatch(self, request):
        c = self.ctl
        op = request.get('op')
        if op == 'frame':
            return dict(media=self.media(request))
        self.update(request)
        if op == 'select':
            name = request['name']
            index = c.models.index_of_name(name)
            if index < 0:
                raise ValueError('Model is no longer available')
            c.setMode('')
            c.selectModel(index)
        elif op == 'mode':
            c.setMode(request['name'])
        elif op == 'generate':
            c.generate(submission(self.settings, c), int(self.settings['count']))
        elif op == 'view':
            self.set_view(request.get('path', ''))
        elif op == 'playback':
            if self.player and self.view_path:
                if self.player.isPlaying():
                    self.player.pause()
                else:
                    self.player.play()
        elif op == 'cancel':
            c.cancel()
        elif op == 'rescan':
            c.rescan()
            c.gallery.load_existing()
        elif op == 'input':
            c.setInputImage(request.get('path', ''))
        elif op == 'last':
            c.setLastImage(request.get('path', ''))
        elif op == 'reference':
            c.addEditImage(request['path'])
        elif op == 'clear_references':
            c.clearEditImages()
            c.clearInputImage()
            c.clearLastImage()
            self.settings.update(useInputImage=False, useLastFrame=False, useReferences=False)
            self.revision += 1
        elif op == 'loras':
            choices = {r['name']: r for r in c.choices._rows if r['ok']}
            rows = request['rows']
            for row in rows:
                if row['name'] not in choices or not math.isfinite(float(row['strength'])):
                    raise ValueError('Invalid or incompatible LoRA')
                row['patchesClip'] = bool(choices[row['name']].get('patches_clip'))
            c.loras.clear()
            c.restoreLoras(rows)
        elif op == 'restore':
            self.restore(request['path'])
        elif op == 'open':
            self.open(self.output_path(request['path']))
        elif op == 'folder':
            self.open(str(__import__('gallery').OUT_DIR))
        elif op not in ('hello', 'poll', 'settings'):
            raise ValueError('Unknown request')
        if op not in ('poll', 'hello', 'settings', 'view', 'playback'):
            self.save()
        return self.snapshot(request)

    def open(self, path):
        if self.desktop_env is None:
            raise ValueError('Opening desktop applications is disabled in this engine')
        subprocess.Popen(['xdg-open', path], env=self.desktop_env, start_new_session=True)

    def output_path(self, path):
        if not self.ctl.gallery.has_path(path):
            raise ValueError('Output is no longer in the gallery')
        return path

    def restore(self, path):
        c = self.ctl
        path = self.output_path(path)
        import outmeta
        p = outmeta.params_for(path)
        if not p:
            raise ValueError('This output has no saved generation settings')
        model = p.get('model')
        if model and model != self.model:
            index = c.models.index_of_name(model)
            if index < 0:
                raise ValueError('The output model is unavailable: ' + model)
            c.setMode('')
            c.selectModel(index)
        g = self.settings
        g.update({key: value for key, value in p.items() if key in BASE})
        g.update({key: value for key, value in (p.get('prompt_boxes') or {}).items()
                  if key in ('positive', 'negative')})
        if p.get('width', 0) > 0 and p.get('height', 0) > 0:
            divisor = math.gcd(int(p['width']), int(p['height']))
            g.update(aspectW=int(p['width']) // divisor, aspectH=int(p['height']) // divisor,
                     megapixels=round(p['width'] * p['height'] / 100000) / 10)
        if 'seed' in p:
            g.update(randomSeed=False, reuseSeed=False)
        if 'toggles' in p:
            g.update(negpip=bool(p['toggles'].get('negpip')),
                     modelSampling=bool(p['toggles'].get('model_sampling')))
        if 'model_sampling' in p:
            g['ms'] = copy.deepcopy(p['model_sampling'])
        g['still'] = p.get('kind') == 'still'
        g.update(useInputImage=False, useLastFrame=False, useReferences=False)
        c.clearInputImage()
        c.clearLastImage()
        c.clearEditImages()
        if p.get('edit') or p.get('kind') == 'edit':
            if not c.optionalEditImage:
                c._mode = 'edit'
                c.modeChanged.emit()
        else:
            c.setMode('')
        if p.get('input_image_local'):
            restored = c.restoreInputImage(p['input_image_local'])
            g['useInputImage'] = bool(p.get('use_input_image')) and restored
        if p.get('last_image_local'):
            restored = c.restoreLastImage(p['last_image_local'])
            g['useLastFrame'] = bool(p.get('use_last_frame')) and restored
        c.loras.clear()
        c.restoreLoras(p.get('loras') or [])
        refs = p.get('reference_images_local') or []
        if refs:
            g['useReferences'] = c.restoreInputImage(refs[0])
            c.restoreEditImages(refs[1:])
        self.revision += 1

    def snapshot(self, request):
        c = self.ctl
        c.gallery.setFilter(request.get('filter', ''))
        offset = max(0, int(request.get('offset', 0)))
        gallery = []
        for row in c.gallery._rows[offset:offset + 60]:
            if not row.get('live'):
                c.gallery.requestThumb(row['path'])
            if row['is_video']:
                c.gallery.requestPoster(row['path'])
            gallery.append({k: row.get(k, False if k in ('live', 'grab') else '')
                            for k in ('path', 'name', 'is_video', 'thumb', 'poster', 'live', 'grab')})
        messages = list(self.messages)
        self.messages.clear()
        return dict(model=self.model, models=[{k: v for k, v in row.items() if k != 'entry'}
                                              for row in c.models._rows], modes=c.modes(), mode=c.mode,
                    settings=self.settings, revision=self.revision, heights=self.heights, multiple=self.multiple,
                    media=self.media(request), replacement=self.replacement,
                    flags={key: getattr(c, key) for key in FLAGS},
                    ready=c.ready, busy=c.busy, status=c.status, progress=c.progress,
                    queue=c.queue, elapsed=c.elapsed, messages=messages,
                    samplers=c.samplers, schedulers=c.schedulers, curves=c.curves, outsideWindows=c.outsideWindows,
                    gallery=gallery, total=c.gallery.count, offset=offset,
                    choices=c.choices._rows, loras=c.lorasSnapshot(),
                    input=c.inputImage, last=c.lastImage, references=c.editExtraImages,
                    lastSeed=c.lastSeed)


def run(painter):
    # Save the display only for the GTK child. The Qt controller cannot open
    # a native window or accidentally claim the real clipboard.
    child_env = os.environ.copy()
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ['QT_QPA_PLATFORMTHEME'] = ''
    os.environ['QT_STYLE_OVERRIDE'] = ''
    os.environ.pop('DISPLAY', None)
    os.environ.pop('WAYLAND_DISPLAY', None)
    app = QGuiApplication(['painter-engine'])
    app.setQuitOnLastWindowClosed(False)
    ctl = painter.Painter()
    engine = Engine(ctl, painter.Prefs(), child_env)
    lease = painter.BackendClientLease(ctl.warden, 'comfy', app)
    with tempfile.TemporaryDirectory(prefix='painter-', dir=child_env['XDG_RUNTIME_DIR']) as directory:
        server = Server(Path(directory) / 'engine.sock', engine, app)
        child = subprocess.Popen(['unity-quantal-runtime', '/usr/bin/python',
                                  str(Path(__file__).with_name('unity_frontend.py')),
                                  str(Path(directory) / 'engine.sock')], env=child_env)
        lease.start(lambda ok, _why: None if ok else ctl.startBackend())
        ctl._probe.start()
        ctl._poll_backend()
        app.aboutToQuit.connect(lease.close)
        timer = QTimer(app)
        timer.setInterval(250)
        timer.timeout.connect(lambda: app.quit() if child.poll() is not None else None)
        timer.start()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: app.quit())
        try:
            code = app.exec()
        finally:
            lease.close()
            engine.save()
            server.server.close()
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        return child.returncode or code
