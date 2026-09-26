"""Player's disposable renderer process. stdin: JSON; stdout: framed size/state.

A separate EGL context/process keeps renderer faults out of playback and works
with both Qt Quick's native Plasma and Hyprland graphics backends. One frame
in flight bounds memory and display latency; Player acknowledges scene-graph
consumption before the next frame. Pixels use a private memfd when provided;
inline RGBA remains compatible with already-running older Player instances.
"""
import ctypes as C
import json
import io
import math
import mmap
import os
from pathlib import Path
import select
import shutil
import signal
import struct
import sys
import tempfile
import time

from build import prepare
from native import load_renderer
from player_audio import PlayerAudio
from settings import DEFAULTS, DIALS, LOOK_DIALS, PARTICLE_RATE, TOGGLES
from shared_dials import SharedDials


def send(kind, payload):
    if kind == b'J':
        payload = json.dumps(payload).encode()
    sys.stdout.buffer.write(kind+struct.pack('!I', len(payload))+payload)
    sys.stdout.buffer.flush()


def read_json(path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return fallback


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.'+path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out, indent=1)
            out.write('\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Engine:
    def __init__(self, library):
        self.lib = load_renderer(str(library))
        self.state = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'gforce-vis'
        self.shared = SharedDials(DEFAULTS, self.state)
        saved = read_json(self.state/'dials.json', {})
        if not isinstance(saved, dict): saved = {}
        if 'sceneScale' in saved:
            value = saved.pop('sceneScale')
            for key in ('waveScale','particleScale','distortionScale'):
                saved.setdefault(key,value)
        self.values = dict(DEFAULTS)
        self.values.update(self.shared.read(saved))
        self.choices, self.selections = {}, {}
        self.paused = False
        self.dirty_at = None
        self.error = ''
        self.presets = []
        self.load_presets()
        self.comparison = None
        self.ready = False
        self.require(self.lib.gf_headless(1920, 1080))
        self.require(self.lib.gf_init(640, 360))
        self.ready = True
        self.apply_all()
        self.width, self.height = 640, 360
        self.frame_map = None
        frame_file = os.environ.get('GF_PLAYER_FRAME_FILE')
        if frame_file:
            with open(frame_file,'r+b') as file:
                self.frame_map = mmap.mmap(file.fileno(),1920*1080*4)
        pixel_type = C.c_ubyte*(1920*1080*4)
        self.pixels = pixel_type.from_buffer(self.frame_map) if self.frame_map is not None else pixel_type()
        self.pcm = (C.c_float*550)()
        self.started = time.monotonic()

    def require(self, ok):
        if not ok:
            raise RuntimeError((self.lib.gf_error() or b'could not create renderer').decode())

    def set_value(self, name, value):
        bounds = {n:(lo,hi) for n,_,lo,hi,_,_ in DIALS}
        if name in bounds:
            value = float(value)
            if not math.isfinite(value): return
            lo, hi = bounds[name]
            value = max(lo, min(hi, value))
        elif name in dict(TOGGLES):
            value = bool(value)
        else:
            return
        self.values[name] = value
        if name == 'transitionLo' and value > self.values['transitionHi']:
            self.set_value('transitionHi', value)
        if name == 'transitionHi' and value < self.values['transitionLo']:
            self.set_value('transitionLo', value)
        if name == 'rate':
            self.lib.gf_set_interval(ord('R'), (f'{value:.3f}*'+PARTICLE_RATE).encode())
        elif name != 'hitHold':
            v = .5**(1/value) if name == 'persist' else value/255 if name == 'fadeBias' else value
            self.require(self.lib.gf_set(name.encode(), v))

    def apply_all(self):
        for name, *_ in DIALS:
            self.set_value(name, self.values.get(name, DEFAULTS[name]))
        for name, _ in TOGGLES:
            self.set_value(name, self.values.get(name, DEFAULTS[name]))
        for kind, pair in self.values['intervals'].items():
            if kind in 'WDCP' and len(pair) == 2:
                a,b = [max(0., min(300., float(v))) for v in pair]
                self.lib.gf_set_interval(ord(kind), f'{a} + rnd( {b} )'.encode())

    def save(self):
        if self.comparison is not None:
            self.dirty_at = None
            return
        # Preserve standalone panel visibility: Player owns its own preference.
        existing = read_json(self.state/'dials.json', {})
        data = dict(self.values)
        data.pop('panel', None)
        if isinstance(existing, dict) and 'panel' in existing:
            data['panel'] = existing['panel']
        atomic_json(self.state/'dials.json', data)
        self.shared.save(data)
        self.dirty_at = None

    def load_presets(self):
        data = read_json(self.state/'presets.json', [])
        self.presets = [p for p in data if isinstance(p, dict) and p.get('components')] if isinstance(data, list) else []

    def command(self, msg):
        op = msg.get('op')
        if op == 'dial':
            self.set_value(msg['name'], msg['value'])
        elif op == 'interval':
            kind = msg['kind']
            if kind not in ('W','D','C','P'): return
            lo, hi = sorted(max(0, min(300, float(v))) for v in msg['value'])
            self.values['intervals'] = {**self.values['intervals'], kind:[lo, hi-lo]}
            self.apply_all()
        elif op == 'key':
            key = msg['key']
            if key not in ('w','c','x','n','p','r',' '): return
            self.lib.gf_key(ord(key))
        elif op == 'select':
            if msg['kind'] not in ('W','D','C','P'): return
            self.require(self.lib.gf_select(ord(msg['kind']), msg['name'].encode()))
        elif op == 'savePreset':
            comps = [line.split('\t') for line in self.lib.gf_preset_capture().decode().splitlines() if line.count('\t')==2]
            comps = [[k,n,int(seed)] for k,n,seed in comps]
            name = ' · '.join(n.replace('_',' ') for k,n,_ in comps if k in 'WDC')
            self.load_presets()
            self.presets.append({'name':name, 'saved':time.strftime('%Y-%m-%dT%H:%M:%S'),
                                 'components':comps,
                                 'dials':{k:self.values[k] for k in (*LOOK_DIALS,'forceConnect','forcePoints')}})
            atomic_json(self.state/'presets.json', self.presets)
        elif op in ('preset','deletePreset'):
            self.load_presets()
            index = int(msg['index'])
            if not 0 <= index < len(self.presets): return
            if op == 'deletePreset':
                self.presets.pop(index)
                atomic_json(self.state/'presets.json', self.presets)
            else:
                if self.comparison is not None: self.compare()
                preset = self.presets[index]
                self.lib.gf_preset_clear_particles()
                for kind,name,seed in preset['components']:
                    self.require(self.lib.gf_preset_recall(ord(kind),name.encode(),int(seed),1))
                for name,value in preset.get('dials',{}).items():
                    self.set_value(name,value)
                self.lib.gf_set(b'paused',1)
        elif op == 'reset':
            if self.comparison is not None: return
            self.values = dict(DEFAULTS)
            self.apply_all()
        elif op == 'compare':
            self.compare()
        else:
            return
        self.dirty_at = time.monotonic()+.3

    def compare(self):
        if self.comparison is None:
            self.save()
            self.comparison = (self.values, self.paused)
            self.values = dict(DEFAULTS)
            self.lib.gf_set(b'paused',1)
        else:
            self.values, paused = self.comparison
            self.comparison = None
            self.lib.gf_set(b'paused',int(paused))
        self.apply_all()

    def snapshot(self, status):
        state = (C.c_long*6)()
        self.lib.gf_control_state(state)
        self.paused = bool(state[0])
        self.values['particles'] = bool(self.lib.gf_get(b'particles'))
        return {'values':self.values, 'paused':self.paused, 'comparing':self.comparison is not None,
                'presets':[p['name'] for p in self.presets],
                'choices':{k:self.lib.gf_choices(ord(k)).decode().splitlines() for k in 'WDCP'},
                'selections':{k:self.lib.gf_selection(ord(k)).decode() for k in 'WDCP'},
                'status':self.error or status, 'ready':True,
                'renderWidth':round(self.lib.gf_get(b'renderWidth')),
                'renderHeight':round(self.lib.gf_get(b'renderHeight'))}

    def frame(self, audio):
        now = time.monotonic()
        self.pcm[:] = audio.sample(now, self.values['hitHold'])
        self.require(self.lib.gf_resize(self.width, self.height))
        self.require(self.lib.gf_frame(self.pcm, round((now-self.started)*1000), 0))
        self.lib.gf_read(self.pixels, self.width, self.height)
        header = struct.pack('!II', self.width, self.height)
        return header if self.frame_map is not None else header+C.string_at(self.pixels,self.width*self.height*4)

    def close(self):
        try:
            if self.comparison is not None: self.compare()
            if self.dirty_at is not None and self.comparison is None: self.save()
        finally:
            if self.ready: self.lib.gf_close()
            self.lib.gf_headless_close()
            if self.frame_map is not None:
                del self.pixels
                self.frame_map.close()
                self.frame_map = None


def main():
    # A private engine file prevents simultaneous standalone/Player engines
    # from overwriting each other's component state; looks and dials are shared.
    state = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'gforce-vis'
    engine_state = Path(os.environ.get('GF_ENGINE_STATE_DIR', str(state/'player-engine')))
    engine_state.mkdir(parents=True, exist_ok=True)
    original = state/'engine/.G-Force'
    if not (engine_state/'.G-Force').exists() and original.is_file():
        shutil.copy2(original, engine_state/'.G-Force')
    os.environ['GF_ENGINE_STATE_DIR'] = str(engine_state)
    library = os.environ.get('GF_RENDERER_PATH') or prepare()
    # Native engine diagnostics also use stdout. Keep the protocol descriptor
    # separate and route all C/Python diagnostics to stderr.
    protocol = os.fdopen(os.dup(1), 'wb', buffering=0)
    os.dup2(2,1)
    sys.stdout = io.TextIOWrapper(protocol, encoding="utf-8")
    engine = Engine(library)
    audio = PlayerAudio(sys.argv[1])
    running = True
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    os.set_blocking(0,False)
    pending, ack, next_frame, next_state = bytearray(), True, 0., 0.
    report_start, report_frames, actual_fps = time.monotonic(), 0, 0.
    try:
        while running:
            now = time.monotonic()
            if select.select([0], [], [], max(0, min(.05, next_frame-now)) if ack else .05)[0]:
                chunk = os.read(0,65536)
                if not chunk: break
                pending.extend(chunk)
                while b'\n' in pending:
                    line, _, pending = pending.partition(b'\n')
                    msg = json.loads(line)
                    if msg.get('op') == 'ack': ack = True
                    elif msg.get('op') == 'size':
                        w,h = max(1,int(msg['width'])), max(1,int(msg['height']))
                        scale = min(1.,1920/w,1080/h)
                        engine.width,engine.height = max(1,round(w*scale)),max(1,round(h*scale))
                    else:
                        try: engine.command(msg)
                        except (OSError,ValueError,RuntimeError) as exc: engine.error = str(exc)
                        next_state = 0.
            now = time.monotonic()
            if engine.dirty_at is not None and now >= engine.dirty_at:
                try: engine.save()
                except OSError as exc:
                    engine.error = 'could not save visualizer settings: '+str(exc)
                    engine.dirty_at = None
            if now >= next_state:
                state = engine.snapshot(audio.status)
                if now-report_start >= 1.:
                    actual_fps = report_frames/(now-report_start)
                    report_start, report_frames = now, 0
                state['actualFps'] = actual_fps
                send(b'J',state)
                next_state = now+1.
            if ack and now >= next_frame:
                send(b'M' if engine.frame_map is not None else b'F',engine.frame(audio))
                ack = False
                report_frames += 1
                interval = 1/max(15,engine.values['fps'])
                # Keep cadence without dropping an extra interval for a late
                # ACK, or trying to catch up with a burst after a long stall.
                next_frame += interval
                if next_frame <= now:
                    next_frame = now+interval
    finally:
        audio.close()
        engine.close()


if __name__ == '__main__':
    try: main()
    except (OSError,ValueError,RuntimeError) as exc:
        print(f'Visualizer: {exc}',file=sys.stderr)
        sys.exit(1)
