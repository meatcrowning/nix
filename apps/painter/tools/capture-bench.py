#!/usr/bin/env python3
"""Measure MOSS capture on/off on an already-running isolated backend only.

Requires its PID, a non-production loopback port, scratch input/output/user/db,
and a finite cgroup memory cap. Never starts services or changes a live backend.
Run from a guarded offscreen shell with Comfy-capable Painter Python. Outputs
JSONL measurements; capture remains enabled by default in ordinary generation.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

APP = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(APP), str(APP.parent / 'pylib')]


def verify_isolation(pid, url, scratch):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', '::1') or parsed.port in (None, 8188):
        raise ValueError('Use a separate loopback backend on a non-production port')
    if Path('/proc/%d' % pid).stat().st_uid != os.getuid():
        raise ValueError('Backend must belong to the current user')
    argv = Path('/proc/%d/cmdline' % pid).read_bytes().decode().split('\0')
    def value(flag):
        if flag not in argv:
            raise ValueError('Missing isolated backend flag: ' + flag)
        return argv[argv.index(flag) + 1]
    if int(value('--port')) != parsed.port or value('--listen') not in ('127.0.0.1', '::1'):
        raise ValueError('URL does not match backend command line')
    scratch = scratch.resolve(strict=True)
    if scratch in (Path('/'), Path.home(), Path.home() / 'Pictures'):
        raise ValueError('Choose a dedicated scratch directory')
    dirs = [Path(value('--' + kind + '-directory')).resolve(strict=True)
            for kind in ('input', 'output', 'user')]
    if any(not p.is_relative_to(scratch) or p == scratch for p in dirs) or len(set(dirs)) != 3:
        raise ValueError('Input/output/user must be separate directories inside scratch')
    database = value('--database-url')
    if not database.startswith('sqlite:///'):
        raise ValueError('Benchmark requires an explicit scratch SQLite database')
    db = Path(database[len('sqlite:///'):]).resolve()
    if not db.is_relative_to(scratch):
        raise ValueError('Database is outside scratch')
    groups = Path('/proc/%d/cgroup' % pid).read_text().splitlines()
    group = next(line.split(':', 2)[2] for line in groups if line.startswith('0::'))
    cap = (Path('/sys/fs/cgroup') / group.lstrip('/') / 'memory.max').read_text().strip()
    if cap == 'max' or int(cap) <= 0:
        raise ValueError('Backend needs a finite cgroup memory.max cap')
    return dirs[1]


def request(url, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url.rstrip('/') + path, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def sample_memory(pid):
    try:
        rss = next(int(line.split()[1]) * 1024 for line in Path('/proc/%d/status' % pid).read_text().splitlines()
                   if line.startswith('VmRSS:'))
    except (OSError, StopIteration):
        rss = 0
    gpu = None
    try:
        lines = subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid,used_memory',
                                         '--format=csv,noheader,nounits'], timeout=2, stderr=subprocess.DEVNULL).decode().splitlines()
        memory = [int(line.split(',')[1]) * 1024**2 for line in lines if int(line.split(',')[0]) == pid]
        gpu = sum(memory) if memory else 0
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return rss, gpu


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend-pid', required=True, type=int)
    p.add_argument('--url', required=True)
    p.add_argument('--scratch-root', required=True, type=Path)
    p.add_argument('--models', required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--prompt', default='A red cube and a blue sphere on a white table.')
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--steps', type=int, default=20)
    p.add_argument('--width', type=int, default=1024)
    p.add_argument('--height', type=int, default=1024)
    p.add_argument('--rounds', type=int, default=2)
    p.add_argument('--timeout', type=float, default=900)
    p.add_argument('--warden-url', default='http://127.0.0.1:8199')
    args = p.parse_args()
    out = verify_isolation(args.backend_pid, args.url, args.scratch_root)
    if args.rounds < 1 or args.rounds > 20 or args.timeout <= 0:
        p.error('Use 1–20 rounds and a positive timeout')
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE'):
        env.pop(key, None)
    os.environ.clear()
    os.environ.update(env)
    subprocess.run(['bash', '-c', 'source tools/lib/session-guard.sh; sg_require_offscreen'],
                   cwd=APP.parents[1], check=True, env=env)
    from PySide6.QtCore import QCoreApplication, QEventLoop
    from comfy import ComfyClient
    from registry import Registry, Overrides
    reg = Registry(args.models, Overrides(str(args.scratch_root / 'overrides.json')))
    entry = reg.find(args.model)
    if entry is None or entry.family != 'moss_image':
        raise ValueError('Select an available MOSS image model')
    queue = request(args.url, '/queue')
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise ValueError('Isolated backend must have an empty queue')
    info = request(args.url, '/object_info')
    if not {'PainterMossSampler', 'PainterMossSaveImage'} <= info.keys():
        raise ValueError('Isolated backend does not advertise MOSS capture')
    app = QCoreApplication([])
    client = ComfyClient(args.url)
    token = 'capture-bench-' + uuid.uuid4().hex
    claim = dict(backend='comfy', token=token, lease=120)
    pairing = reg.pair(entry)
    weights = sum(getattr(pairing.get(key), 'size', 0) for key in ('model', 'encoder', 'vae'))
    lease = request(args.warden_url, '/reserve-owned', dict(claim, bytes=weights))
    if not lease.get('ok'):
        raise RuntimeError('Warden refused benchmark: ' + str(lease.get('reason')))
    try:
        client.connect_ws()
        connected = []
        client.connected.connect(lambda: connected.append(True))
        deadline = time.monotonic() + 15
        while not connected and time.monotonic() < deadline:
            app.processEvents(QEventLoop.AllEvents, 50)
            time.sleep(.01)
        if not connected:
            raise RuntimeError('Isolated websocket did not connect')
        # First pair warms each graph; subsequent pairs alternate order.
        for pair in range(args.rounds + 1):
            for capture in ((False, True) if pair % 2 == 0 else (True, False)):
                verify_isolation(args.backend_pid, args.url, args.scratch_root)
                # Different seeds per pair prevent Comfy's output cache from
                # skipping sampling, while on/off within a pair shares a seed.
                params = dict(positive=args.prompt, seed=args.seed + pair, steps=args.steps,
                              width=args.width, height=args.height, moss_capture=capture,
                              filename_prefix='benchmark/' + uuid.uuid4().hex)
                built = reg.build(entry, params, object_info=info)
                ended = []
                def finished(job, *unused):
                    ended.append(job)
                client.jobFinished.connect(finished)
                client.jobFailed.connect(finished)
                started = time.monotonic()
                job = client.submit(built['prompt'], built['params'])
                rss_peak = 0
                gpu_peak = None
                next_sample = next_renew = 0
                try:
                    while not ended and time.monotonic() - started < args.timeout:
                        app.processEvents(QEventLoop.AllEvents, 50)
                        now = time.monotonic()
                        if now >= next_sample:
                            rss, gpu = sample_memory(args.backend_pid)
                            rss_peak = max(rss_peak, rss)
                            if gpu is not None:
                                gpu_peak = max(gpu_peak or 0, gpu)
                            next_sample = now + 1
                        if now >= next_renew:
                            if not request(args.warden_url, '/renew-owned', claim).get('ok'):
                                raise RuntimeError('Benchmark reservation expired')
                            next_renew = now + 30
                        time.sleep(.01)
                    if not ended or job.error:
                        client.cancel_all()
                        for _ in range(50):
                            app.processEvents(QEventLoop.AllEvents, 20)
                            time.sleep(.01)
                        raise RuntimeError(job.error or 'Benchmark timed out')
                    output_bytes = sum((out / image.get('subfolder', '') / image['filename']).stat().st_size for image in job.images)
                    print(json.dumps(dict(capture=capture, warmup=pair == 0, seed=params['seed'],
                                          backend_seconds=job.duration, wall_seconds=time.monotonic() - started,
                                          sampled_rss_peak=rss_peak, sampled_gpu_peak=gpu_peak,
                                          output_bytes=output_bytes, prompt_id=job.prompt_id)), flush=True)
                finally:
                    client.jobFinished.disconnect(finished)
                    client.jobFailed.disconnect(finished)
                    if job.terminal:
                        client.acknowledge(job)
    finally:
        client.close()
        request(args.warden_url, '/done-owned', claim)


if __name__ == '__main__':
    main()
