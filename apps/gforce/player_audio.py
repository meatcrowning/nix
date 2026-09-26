"""A passive tap of one Player stream's output ports, upstream of every sink.

No monitor, default source, or playback link is ever selected. The recorder
cannot autoconnect; only explicit, channel-matched links from the named stream
are created. Its lifetime is the visualizer worker's lifetime.
"""
from array import array
import json
import os
import select
import subprocess
import threading
import time

from audio_window import AudioWindow


def props(obj):
    return obj.get('info', {}).get('props', {})


def tap_ports(graph, player_name, recorder_name):
    sources = [o for o in graph if o['type'].endswith(':Node')
               and props(o).get('media.class') == 'Stream/Output/Audio'
               and props(o).get('node.name') == player_name]
    targets = [o for o in graph if o['type'].endswith(':Node')
               and props(o).get('node.name') == recorder_name]
    if len(sources) != 1 or len(targets) != 1:
        return None, []
    source, target = sources[0], targets[0]
    def ports(node, direction):
        return {props(o).get('audio.channel'): props(node)['node.name']+':'+props(o)['port.name'] for o in graph
                if o['type'].endswith(':Port')
                and str(props(o).get('node.id')) == str(node['id'])
                and props(o).get('port.direction') == direction
                and props(o).get('audio.channel')}
    outputs, inputs = ports(source, 'out'), ports(target, 'in')
    # A mono stream feeds both display channels. For surround, use the front
    # pair; never sum unrelated ports or infer a sink from existing links.
    pairs = [(outputs.get(ch, outputs.get('MONO')), inputs[ch])
             for ch in ('FL', 'FR') if ch in inputs]
    if len(pairs) != 2 or any(a is None for a, _ in pairs):
        return None, []
    return (source['id'], props(source).get('object.serial')), pairs


class PlayerAudio:
    def __init__(self, player_name):
        self.name = player_name
        self.recorder_name = f'player-visualizer-tap-{os.getpid()}'
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.audio = AudioWindow()
        self.last_audio = 0.
        self.linked = None
        self.router = None
        self.status = 'waiting for Player audio'
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def sample(self, now, hold):
        with self.lock:
            return self.audio.sample(now, hold) if now-self.last_audio < .2 else (0.,)*550

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=6)
        if self.router is not None:
            self.router.join(timeout=6)

    def route(self):
        # Graph inspection can block for seconds. Never put it on the PCM
        # reader: doing so starves the renderer at each polling interval.
        while not self.stop_event.is_set():
            try:
                graph = json.loads(subprocess.check_output(['pw-dump'], timeout=2))
                if self.stop_event.is_set():
                    return
                identity, pairs = tap_ports(graph, self.name, self.recorder_name)
                nodes = {o['id']:props(o).get('node.name') for o in graph if o['type'].endswith(':Node')}
                ports = {o['id']:str(nodes.get(int(props(o).get('node.id',-1))))+':'+str(props(o).get('port.name'))
                         for o in graph if o['type'].endswith(':Port')}
                present = {(ports.get(o['info'].get('output-port-id')), ports.get(o['info'].get('input-port-id')))
                           for o in graph if o['type'].endswith(':Link')}
                for output, input_ in pairs:
                    if self.stop_event.is_set():
                        return
                    if (output, input_) not in present:
                        subprocess.run(['pw-link', '-L', '-p', '{"link.passive":true}',
                                        output, input_], check=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=2)
                with self.lock:
                    if identity != self.linked:
                        self.audio = AudioWindow()
                        self.last_audio = 0.
                    self.linked = identity
                self.status = '' if pairs else 'waiting for Player audio'
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                with self.lock:
                    self.linked = None
                    self.last_audio = 0.
                self.status = f'Player audio unavailable: {exc}'
            self.stop_event.wait(1.)

    def run(self):
        capture = None
        try:
            capture = subprocess.Popen([
                'pw-record', '--target=0', '--raw', '--format=f32', '--rate=22050',
                '--channels=2', '--channel-map=FL,FR', '--latency=25ms',
                '--properties='+json.dumps({'node.name': self.recorder_name,
                    'node.autoconnect': False, 'node.dont-reconnect': True,
                    'node.dont-fallback': True, 'node.passive': True}), '-'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            os.set_blocking(capture.stdout.fileno(), False)
            pending = bytearray()
            self.router = threading.Thread(target=self.route, daemon=True)
            self.router.start()
            while not self.stop_event.is_set() and capture.poll() is None:
                if not select.select([capture.stdout], [], [], .05)[0]:
                    continue
                chunk = os.read(capture.stdout.fileno(), 65536)
                if not chunk:
                    break
                pending.extend(chunk)
                count = len(pending)//8*8
                stereo = array('f', pending[:count])
                del pending[:count]
                if stereo:
                    mono = array('f', ((stereo[i]+stereo[i+1])*.5 for i in range(0,len(stereo),2)))
                    with self.lock:
                        if self.linked is not None:
                            now = time.monotonic()
                            self.audio.feed(mono.tobytes(), now)
                            self.last_audio = now
            if not self.stop_event.is_set():
                self.status = 'Player audio capture stopped; reopen Visualizer to retry'
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.status = f'Player audio unavailable: {exc}'
        finally:
            self.stop_event.set()
            if capture:
                if capture.poll() is None:
                    capture.terminate()
                    try:
                        capture.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        capture.kill()
                        capture.wait()
                capture.stdout.close()
