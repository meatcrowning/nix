"""Local, versioned control of an existing Qt Painter window.

The client/discovery half is stdlib-only. Server requests run on Qt's UI thread.
One newline-delimited JSON request produces {ok, state} or {ok: false, error}.
"""
import copy
import json
import math
import os
from pathlib import Path
import socket
import tempfile
import time

VERSION = 1
LIMIT = 2 * 1024 * 1024


def runtime_root():
    return Path(os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir())


def request(path, payload, timeout=3):
    data = json.dumps(payload, allow_nan=False).encode() + b'\n'
    if len(data) > LIMIT:
        raise ValueError('Request exceeds 2 MiB')
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(path))
        sock.sendall(data)
        buf = bytearray()
        while b'\n' not in buf:
            sock.settimeout(max(.001, deadline - time.monotonic()))
            chunk = sock.recv(65536)
            if not chunk:
                raise ValueError('Painter closed the connection without a reply')
            buf.extend(chunk)
            if len(buf) > 4 * LIMIT:
                raise ValueError('Painter reply is too large')
        result = json.loads(buf.split(b'\n', 1)[0])
        if not result.get('ok'):
            raise ValueError(result.get('error', 'Painter refused the request'))
        return result['state']


def discover():
    found = []
    for path in sorted(runtime_root().glob('painter-agent-%s-*/control.sock' % os.getuid())):
        try:
            state = request(path, {'op': 'state'}, timeout=.5)
            found.append(dict(socket=str(path), pid=state['pid'], model=state['model'],
                              mode=state['mode'], busy=state['busy']))
        except (OSError, ValueError, KeyError):
            continue  # Crashed instances are ignored, never unlinked by a client.
    return found


def target(path=None):
    if path:
        return path
    windows = discover()
    if len(windows) != 1:
        raise ValueError('Expected one Painter window; found %d. Use list and --socket.' % len(windows))
    return windows[0]['socket']


BOUNDS = {
    'count': (1, 100), 'batch_size': (1, 64), 'steps': (1, 1000),
    'aspectW': (1, 999), 'aspectH': (1, 999), 'seed': (-1, 2**53 - 1),
    'cfg': (0, 100), 'denoise': (0, 1), 'duration': (.1, 120), 'fps': (1, 120),
    'megapixels': (.01, 16), 'editMegapixels': (.01, 16),
    'reference_megapixels': (.01, 16), 'krea_shift': (0, 100),
    'slg_start_percent': (0, 1), 'slg_end_percent': (0, 1),
}
INTEGERS = {'count', 'batch_size', 'steps', 'aspectW', 'aspectH', 'seed'}
FLAGS = ('layoutSupport', 'isVideo', 'isEdit', 'editSampling', 'editPatches',
         'supportsLoras', 'encoderControls', 'referenceImages', 'optionalEditImage',
         'fixedSampling', 'nativeScheduler')


def keys(value, allowed, label):
    if not isinstance(value, dict):
        raise ValueError(label + ' must be an object')
    unknown = value.keys() - set(allowed)
    if unknown:
        raise ValueError('Unknown %s: %s' % (label, ', '.join(sorted(unknown))))


def typed(value, prototype, name):
    if isinstance(prototype, bool):
        valid = type(value) is bool
    elif isinstance(prototype, (int, float)):
        try:
            valid = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            valid = False
    else:
        valid = isinstance(value, type(prototype))
    if not valid:
        raise ValueError('Invalid ' + name)


class Controller:
    def __init__(self, root, ctl):
        self.root, self.ctl = root, ctl

    def gen(self):
        value = self.root.property('gen')
        return value.toVariant() if hasattr(value, 'toVariant') else value

    def invoke(self, name, *args):
        from PySide6.QtCore import QMetaObject, Q_ARG
        if not QMetaObject.invokeMethod(self.root, name, *[Q_ARG('QVariant', arg) for arg in args]):
            raise ValueError('Painter could not apply ' + name)

    def state(self):
        c = self.ctl
        return dict(version=VERSION, pid=os.getpid(), model=c.selectedName, mode=c.mode,
                    settings=self.gen(), input=c.inputImage, last=c.lastImage,
                    references=c.editExtraImages, loras=c.lorasSnapshot(),
                    busy=c.busy, queue=c.queue, status=c.status, ready=c.ready,
                    capabilities={key: getattr(c, key) for key in FLAGS})

    def describe(self):
        from parameter_compare import BASE
        c = self.ctl
        return dict(version=VERSION, operations=['state', 'describe', 'select', 'apply', 'generate'],
                    settings={key: dict(type=type(value).__name__, bounds=BOUNDS.get(key))
                              for key, value in BASE.items() if key not in ('width', 'height')},
                    models=[dict(name=row['name']) for row in c.models._rows], modes=c.modes(),
                    loras=[dict(row) for row in c.choices._rows],
                    samplers=c.samplers, schedulers=c.schedulers,
                    nativeScheduler=c.nativeScheduler, curves=c.curves, outsideWindows=c.outsideWindows)

    def settings(self, values):
        from parameter_compare import BASE
        keys(values, BASE.keys() - {'width', 'height'}, 'settings')
        patch = copy.deepcopy(values)
        for key, value in patch.items():
            typed(value, BASE[key], key)
            if key in BOUNDS:
                low, high = BOUNDS[key]
                if not low <= value <= high or (key in INTEGERS and int(value) != value):
                    raise ValueError('Out of range: ' + key)
        for key, options in [('sampler_name', self.ctl.samplers),
                             ('scheduler', self.ctl.schedulers + [self.ctl.nativeScheduler]),
                             ('krea_sampling', ['native', 'manual', 'turbo_fixed'])]:
            if key in patch and patch[key] not in options:
                raise ValueError('Unknown ' + key)
        if 'ms' in patch:
            keys(patch['ms'], BASE['ms'], 'model sampling settings')
            for key, value in patch['ms'].items():
                typed(value, BASE['ms'][key], 'ms.' + key)
                limits = {'shift_start': (0, 100), 'shift_end': (0, 100),
                          'start_percent': (0, 1), 'end_percent': (0, 1), 'multiplier': (0, 10)}
                if key in limits and not limits[key][0] <= value <= limits[key][1]:
                    raise ValueError('Out of range: ms.' + key)
            for key, options in [('curve', self.ctl.curves), ('outside_window', self.ctl.outsideWindows)]:
                if key in patch['ms'] and patch['ms'][key] not in options:
                    raise ValueError('Unknown ms.' + key)
        if 'moss_layout' in patch and patch['moss_layout']:
            if not self.ctl.layoutSupport:
                raise ValueError('This model does not support layouts')
            from moss_layout import valid
            try:
                patch['moss_layout'] = valid(patch['moss_layout'])
            except (AttributeError, KeyError, TypeError) as exc:
                raise ValueError('Malformed layout document') from exc
        if 'seed' in patch:
            patch.setdefault('randomSeed', patch['seed'] < 0)
            patch.setdefault('reuseSeed', False)
        return patch

    def image(self, value):
        if not isinstance(value, str):
            raise ValueError('Image paths must be strings')
        if not value:
            return ''
        from PySide6.QtGui import QImageReader
        path = str(Path(value).expanduser().resolve())
        usable, reason = self.ctl._usable_image(path, 'provide')
        if not usable or not QImageReader(path).canRead():
            raise ValueError(reason or 'Cannot decode image: ' + path)
        return path

    def apply(self, req):
        c = self.ctl
        patch = self.settings(req.get('settings', {}))
        images = {key: self.image(req[key]) for key in ('input', 'last') if key in req}
        refs = None
        if 'references' in req:
            if not isinstance(req['references'], list) or len(req['references']) > 64:
                raise ValueError('references must be an array of at most 64 image paths')
            refs = list(dict.fromkeys(self.image(path) for path in req['references']))
            if '' in refs:
                raise ValueError('Empty reference path; use [] to clear references')
            if refs and not c.editMultipleImages:
                raise ValueError('This model accepts only one input image')
        loras = None
        if 'loras' in req:
            if not isinstance(req['loras'], list) or len(req['loras']) > 64:
                raise ValueError('loras must be an array of at most 64 entries')
            known = {r['name']: r for r in c.choices._rows if r['ok']}
            loras = []
            for row in req['loras']:
                keys(row, ('name', 'strength', 'enabled'), 'LoRA fields')
                name, strength, enabled = row.get('name'), row.get('strength', 1.0), row.get('enabled', True)
                if not isinstance(name, str) or name not in known or not c.supportsLoras:
                    raise ValueError('Unknown or incompatible LoRA')
                typed(strength, 1.0, 'LoRA strength')
                typed(enabled, True, 'LoRA enabled')
                if not -10 <= strength <= 10:
                    raise ValueError('Out of range: LoRA strength')
                loras.append(dict(name=name, strength=strength, enabled=enabled,
                                  patchesClip=bool(known[name].get('patches_clip'))))
        if 'input' in images and c.isVideo:
            patch.setdefault('useInputImage', bool(images['input']))
        if 'last' in images:
            patch.setdefault('useLastFrame', bool(images['last']))
        if c.referenceImages and ('input' in images or refs is not None):
            patch.setdefault('useReferences', bool(images.get('input', c.inputImage)))
        # Validate the entire request before touching any live settings or assets.
        if 'input' in images:
            if images['input']:
                c.setInputImage(images['input'])
            else:
                c.clearInputImage()
        if 'last' in images:
            if images['last']:
                c.setLastImage(images['last'])
            else:
                c.clearLastImage()
        if refs is not None:
            c.clearEditImages()
            c.restoreEditImages(refs)
        if loras is not None:
            c.loras.clear()
            c.restoreLoras(loras)
        self.invoke('agentApply', patch)
        return self.state()

    def dispatch(self, req):
        op = req.get('op')
        allowed = {
            'state': (), 'describe': (), 'select': ('model', 'mode'),
            'apply': ('model', 'settings', 'input', 'last', 'references', 'loras'),
            'generate': ('model',),
        }
        if op not in allowed:
            raise ValueError('Unknown operation')
        keys(req, ('op', *allowed[op]), 'request fields')
        if op == 'describe':
            return self.describe()
        c = self.ctl
        if op == 'select':
            if ('model' in req) == ('mode' in req):
                raise ValueError('Select exactly one model or mode')
            if 'mode' in req:
                if req['mode'] not in [row['id'] for row in c.modes() if row['available']]:
                    raise ValueError('Mode is not available')
                c.setMode(req['mode'])
            else:
                index = c.models.index_of_name(req['model'])
                if index < 0:
                    raise ValueError('Model is not available')
                c.setMode('')
                c.selectModel(index)
        if op in ('apply', 'generate'):
            if not c.selectedName or req.get('model') != c.selectedName:
                raise ValueError('Model changed or is unavailable; read state before applying')
            if op == 'apply':
                return self.apply(req)
            if not c.ready:
                raise ValueError('Backend is not ready')
            self.invoke('submit')
            return dict(requested=True, state=self.state())
        return self.state()


class Endpoint:
    def __init__(self, root, ctl, parent=None, directory=None):
        from unityipc import Server
        self.directory = Path(tempfile.mkdtemp(prefix='painter-agent-%s-' % os.getuid(),
                                               dir=directory or runtime_root()))
        self.path = self.directory / 'control.sock'
        self.controller = Controller(root, ctl)
        try:
            self.server = Server(self.path, self.controller, parent)
        except Exception:
            self.directory.rmdir()
            raise

    def close(self):
        for sock in list(self.server.clients):
            sock.abort()
        self.server.server.close()
        self.path.unlink(missing_ok=True)
        self.directory.rmdir()
