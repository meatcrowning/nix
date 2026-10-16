"""Non-blocking Redsea bridge: 240 kHz FM multiplex in, verified RDS groups out.

The decoder never opens an SDR or audio device. Its worker owns all pipes;
submit() cannot stall radio playback. Generations fence off results from a
previous tuning, mode, or receive session.
"""

import json
import os
import queue
import shutil
import subprocess
import threading
import time

import numpy as np


class Metadata:
    def __init__(self):
        self.fields = {}
        self.text_ab = None

    def update(self, group):
        if not isinstance(group, dict):
            return None
        pi = group.get("pi")
        if not isinstance(pi, str) or len(pi) != 6 or not pi.startswith("0x"):
            return None
        try:
            int(pi[2:], 16)
        except ValueError:
            return None
        if self.fields.get("pi") != pi:
            self.fields = {"pi": pi}
            self.text_ab = None
        if group.get("rt_ab") in ("A", "B"):
            if self.text_ab != group["rt_ab"]:
                self.fields.pop("radiotext", None)
            self.text_ab = group["rt_ab"]
        for key in ("ps", "radiotext", "prog_type"):
            if isinstance(group.get(key), str):
                self.fields[key] = " ".join(group[key].split())[:256]
        return dict(self.fields)


class Decoder:
    def __init__(self, callback, generation=0, executable=None):
        self.callback = callback
        self.generation = generation
        self.executable = executable or os.environ.get("TUNER_REDSEA") or shutil.which("redsea")
        self.queue = queue.Queue(maxsize=8)
        self.done = threading.Event()
        self.gap = threading.Event()
        self.thread = threading.Thread(target=self._run, name="rds", daemon=True)
        self.thread.start()

    def reset(self, generation):
        self.generation = generation

    def submit(self, mpx, generation):
        if self.done.is_set() or generation != self.generation:
            return
        # Receiver creates a fresh MPX array per block and never mutates it.
        # Hand ownership to the worker; PCM conversion is not audio work.
        try:
            self.queue.put_nowait((generation, mpx))
        except queue.Full:
            # A discontinuity must reacquire bit/group sync, not join stale PCM.
            self.gap.set()

    def close(self):
        self.done.set()
        self.thread.join(timeout=2)

    def _emit(self, generation, data):
        if generation == self.generation and not self.done.is_set():
            self.callback(generation, data)

    @staticmethod
    def _stop(proc):
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=0.3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        proc.stdin.close()
        proc.stdout.close()

    def _run(self):
        proc, current, failed = None, None, False
        pending, output = bytearray(), bytearray()
        metadata = Metadata()
        last_data, last_emit = None, 0.0
        try:
            while not self.done.is_set():
                generation = self.generation
                if generation != current or self.gap.is_set():
                    gap = self.gap.is_set()
                    self.gap.clear()
                    self._stop(proc)
                    proc, current, failed = None, generation, False
                    pending.clear()
                    output.clear()
                    metadata = Metadata()
                    last_data, last_emit = None, 0.0
                    if gap:
                        while True:
                            try:
                                self.queue.get_nowait()
                            except queue.Empty:
                                break
                    self._emit(current, {})
                try:
                    gen, mpx = self.queue.get(timeout=0.01)
                    if gen == current and not failed:
                        pending.extend((np.clip(mpx, -1, 1) * 32767).astype("<i2").tobytes())
                except queue.Empty:
                    pass
                if failed or not pending and proc is None:
                    continue
                try:
                    if proc is None:
                        if not self.executable:
                            raise OSError("RDS decoder is unavailable")
                        proc = subprocess.Popen(
                            [self.executable, "--input", "mpx", "--samplerate", "240000", "--rbds", "--show-partial"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            bufsize=0)
                        os.set_blocking(proc.stdin.fileno(), False)
                        os.set_blocking(proc.stdout.fileno(), False)
                    if pending:
                        try:
                            written = os.write(proc.stdin.fileno(), pending)
                            del pending[:written]
                        except BlockingIOError:
                            pass
                    try:
                        data = os.read(proc.stdout.fileno(), 65536)
                        if not data:
                            raise OSError("RDS decoder stopped")
                        output.extend(data)
                    except BlockingIOError:
                        pass
                    while b"\n" in output:
                        line, _, rest = output.partition(b"\n")
                        output = bytearray(rest)
                        try:
                            group = json.loads(line)
                        except (ValueError, UnicodeError):
                            continue
                        decoded = metadata.update(group)
                        now = time.monotonic()
                        # Unchanged groups only need a freshness heartbeat.
                        if decoded is not None and (decoded != last_data or now - last_emit >= 1):
                            self._emit(current, decoded)
                            last_data, last_emit = decoded, now
                    if len(output) > 65536 or len(pending) > 240000:
                        self.gap.set()
                except OSError as exc:
                    self._emit(current, {"error": str(exc)})
                    self._stop(proc)
                    proc, failed = None, True
                    pending.clear()
        finally:
            self._stop(proc)
