"""Headless controller. Only SSH or the owner's private Unix socket can reach it."""
import base64
from collections import deque
from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import threading
import time

from core import ENGINE, Settings, atomic_json, prepare_run, training_args
from sampling import load_sampling

HERE = Path(__file__).resolve().parent
STATE = Path.home() / '.local/state/moss-trainer'
SOCKET = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'moss-trainer.sock'


def legacy_worker(run=None):
    # Old GUIs have no controller. Never launch another writer beside one.
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            args = path.read_bytes().split(b'\0')
            if str(HERE / 'worker.py').encode() in args:
                if run is None or str(run).encode() in args:
                    return True
        except OSError:
            pass
    return False


class Controller:
    def __init__(self, state=STATE, engine=ENGINE, launch=None):
        self.state_dir = Path(state)
        self.engine = Path(engine)
        self.launch = launch or subprocess.Popen
        self.lock = threading.RLock()
        self.proc = None
        self.run = None
        self.mode = ''
        self.state = 'ready'
        self.events = {}
        self.lines = deque(maxlen=3000)
        self.sequence = 0
        self.generation = ''
        self.started = 0
        self.collecting = False

    def active(self):
        return self.collecting or (self.proc is not None and self.proc.poll() is None)

    def log(self, line):
        self.sequence += 1
        self.lines.append((self.sequence, line))
        if line.startswith('TRAINER:'):
            try:
                event = json.loads(line[8:])
                self.events[event['event']] = event
                if event['event'] == 'status':
                    self.state = event['state']
            except (ValueError, KeyError):
                pass

    def collect(self, proc, logfile):
        try:
            for line in proc.stdout:
                line = line.rstrip('\r\n')
                if logfile:
                    try:
                        logfile.write(line + '\n')
                        logfile.flush()
                    except OSError as exc:
                        with self.lock:
                            self.log('Could not write training log: ' + str(exc))
                        try:
                            logfile.close()
                        except OSError:
                            pass
                        logfile = None
                with self.lock:
                    self.log(line)
            code = proc.wait()
            with self.lock:
                self.state = 'failed' if code else ('stopped' if self.state == 'stopped' else 'completed')
        finally:
            if logfile:
                logfile.close()
            with self.lock:
                self.collecting = False

    def spawn(self, argv, mode, run=None):
        logfile = (run / 'training.log').open('a') if run and mode == 'training' else None
        try:
            self.proc = self.launch(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, errors='replace', bufsize=1)
        except Exception:
            if logfile:
                logfile.close()
            raise
        self.collecting = True
        self.run, self.mode, self.state = run, mode, 'preparing'
        self.events = {}
        self.lines.clear()
        self.started = time.time()
        threading.Thread(target=self.collect, args=(self.proc, logfile), daemon=True).start()

    def describe(self, run):
        manifest = json.loads((run / 'run.json').read_text())
        settings = load_sampling(Settings.from_run(manifest['settings']), run)
        latest = json.loads((run / 'latest.json').read_text()) if (run / 'latest.json').is_file() else None
        return dict(run=str(run), settings=asdict(settings), latest=latest)

    def request(self, doc):
        with self.lock:
            action = doc['action']
            if action == 'status':
                return dict(active=self.active(), mode=self.mode, state=self.state,
                            run=str(self.run) if self.run else '', generation=self.generation,
                            started=self.started, engine=(self.engine / 'revision').is_file(),
                            events=list(self.events.values()), sequence=self.sequence,
                            lines=[(n, s) for n, s in self.lines if n > doc.get('after', 0)])
            if action == 'inspect':
                return self.describe(Path(doc['run']).expanduser().resolve())
            if action == 'samples':
                run = Path(doc['run']).expanduser().resolve()
                return [dict(name=p.name, size=p.stat().st_size, mtime=p.stat().st_mtime_ns)
                        for p in sorted((run / 'sample').glob('*.png')) if p.is_file()]
            if action == 'sample':
                name = doc['name']
                if Path(name).name != name or not name.endswith('.png'):
                    raise ValueError('Invalid sample name')
                path = Path(doc['run']).expanduser().resolve() / 'sample' / name
                if path.stat().st_size > 32 * 1024**2:
                    raise ValueError('Sample exceeds 32 MiB')
                return base64.b64encode(path.read_bytes()).decode()
            if action == 'upload':
                token = doc['token']
                if len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
                    raise ValueError('Invalid upload id')
                path = self.state_dir / 'uploads' / token
                if (path / 'sealed').exists():
                    raise ValueError('This upload is already used by a run; choose a new upload.')
                (path / 'dataset').mkdir(parents=True, exist_ok=True)
                return str(path / 'dataset')
            if action == 'control':
                if not self.active() or self.mode != 'training':
                    raise ValueError('No training worker is running')
                if doc['generation'] != self.generation:
                    raise ValueError('The active job changed; reconnect before controlling it')
                command = doc['message']
                if command.get('command') not in ('pause', 'resume', 'save', 'stop', 'sampling'):
                    raise ValueError('Unknown control')
                self.proc.stdin.write(json.dumps(command) + '\n')
                self.proc.stdin.flush()
                return True
            if action not in ('start', 'resume', 'setup'):
                raise ValueError('Unknown request')
            # Persist request receipts before replying. A lost reply must never
            # turn a reconnect into a second start/resume/setup.
            token = doc['id']
            if len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
                raise ValueError('Invalid request id')
            receipt = self.state_dir / 'requests' / (token + '.json')
            if receipt.exists():
                return json.loads(receipt.read_text())
            if self.active() or legacy_worker():
                raise ValueError('A trainer is already running on top. A pre-controller run must be controlled from its original window.')
            run = None
            if action == 'start':
                settings = Settings(**doc['settings'])
                run = prepare_run(settings)
                upload = Path(settings.dataset).resolve().parent
                if upload.parent == (self.state_dir / 'uploads').resolve():
                    (upload / 'sealed').touch()
                argv = [str(self.engine / '.venv/bin/python'), '-u', str(HERE / 'worker.py'), str(run)]
            elif action == 'resume':
                run = Path(doc['run']).expanduser().resolve()
                latest = json.loads((run / 'latest.json').read_text())
                training_args(run, latest['state'])
                argv = [str(self.engine / '.venv/bin/python'), '-u', str(HERE / 'worker.py'), str(run), '--resume', latest['state']]
            else:
                argv = [sys.executable, '-u', str(HERE / 'setup_engine.py')]
            # Write an intent first: uncertain starts require inspection, never
            # automatic replay, even after an abrupt controller crash.
            result = dict(run=str(run) if run else '', generation=token)
            atomic_json(receipt, result)
            self.generation = token
            self.spawn(argv, 'setup' if action == 'setup' else 'training', run)
            return result


def serve():
    SOCKET.parent.mkdir(parents=True, exist_ok=True)
    with SOCKET.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        SOCKET.unlink(missing_ok=True)
        controller = Controller()
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    request = json.loads(self.rfile.readline(4 * 1024**2))
                    response = {'ok': True, 'value': controller.request(request)}
                except Exception as exc:
                    response = {'ok': False, 'error': str(exc)}
                try:
                    self.wfile.write((json.dumps(response) + '\n').encode())
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Client departure never closes worker stdin.
        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True
        with Server(str(SOCKET), Handler) as server:
            os.chmod(SOCKET, 0o600)
            server.serve_forever()


def rpc():
    request = sys.stdin.buffer.readline(4 * 1024**2)
    def connect():
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(120)
        try:
            sock.connect(str(SOCKET))
        except Exception:
            sock.close()
            raise
        return sock
    try:
        sock = connect()
    except (FileNotFoundError, ConnectionRefusedError):
        subprocess.run(['systemctl', '--user', 'start', 'moss-trainer-controller.service'], check=True,
                       stdout=subprocess.DEVNULL)
        for _ in range(100):
            try:
                sock = connect()
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(.1)
        else:
            raise RuntimeError('Training controller did not start')
    with sock:
        sock.sendall(request)
        with sock.makefile('rb') as stream:
            sys.stdout.buffer.write(stream.readline(48 * 1024**2))


if __name__ == '__main__':
    serve() if '--serve' in sys.argv else rpc()
