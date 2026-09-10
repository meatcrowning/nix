"""Temporary, bounded performance diagnostics; no I/O on the GUI thread.

A worker samples Python stacks when the Qt heartbeat is late. Timed operations
identify work spanning the stall; stack records contain code locations, never
locals, song metadata, URLs or library paths. Disable with PLAYER_PERF_LOG=0.
"""
from collections import deque
from functools import wraps
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
import time

_monitor = None


def timed(name):
    def decorate(fn):
        @wraps(fn)
        def call(*args, **kwargs):
            monitor = _monitor
            if monitor is None:
                return fn(*args, **kwargs)
            started = time.monotonic()
            ident = threading.get_ident()
            active = monitor.active.setdefault(ident, [])
            active.append((name, started))
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed = time.monotonic() - started
                active.pop()
                if elapsed >= .025:
                    monitor.events.append({"event": "slow_operation", "operation": name,
                                           "ms": round(elapsed * 1000, 1), "thread": ident,
                                           "at": time.time()})
        return call
    return decorate


class Monitor:
    def __init__(self, app, directory):
        from PySide6.QtCore import QTimer
        self.events = deque(maxlen=2048)
        self.active = {}
        self.context = {}
        self.context_fn = lambda: {}
        self.last_beat = time.monotonic()
        self.gui_thread = threading.get_ident()
        self.stop = threading.Event()
        self.directory = Path(directory)
        self.timer = QTimer(app)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.beat)
        self.timer.start()
        app.aboutToQuit.connect(self.close)
        self.worker = threading.Thread(target=self.run, name="player-perf-log", daemon=True)
        self.worker.start()

    def beat(self):
        now = time.monotonic()
        gap = now - self.last_beat
        self.last_beat = now
        self.context = self.context_fn()
        if gap >= .250:
            self.events.append({"event": "ui_recovered", "gap_ms": round(gap * 1000, 1),
                                "at": time.time()})

    def close(self):
        self.timer.stop()
        self.stop.set()

    def run(self):
        # Logging failure must never prevent playback or take down the GUI.
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(self.directory / "performance.jsonl",
                                          maxBytes=2 * 1024 * 1024, backupCount=3)
        except OSError as exc:
            print(f"player performance logging unavailable: {exc}", file=sys.stderr)
            return
        def write(record):
            record = {"at": time.time(), "pid": os.getpid(), **self.context, **record}
            handler.emit(logging.LogRecord("player-perf", logging.INFO, "", 0,
                                           json.dumps(record), (), None))
        write({"event": "start", "gui_thread": self.gui_thread,
               "python": sys.version.split()[0]})
        last_sample = 0.0
        last_summary = time.monotonic()
        last_cpu = time.process_time()
        try:
            while not self.stop.wait(.050):
                while self.events:
                    write(self.events.popleft())
                now = time.monotonic()
                lag = now - self.last_beat
                if lag >= .250 and now - last_sample >= 1.0:
                    last_sample = now
                    stacks = {}
                    names = {t.ident: t.name for t in threading.enumerate()}
                    for ident, frame in sys._current_frames().items():
                        if ident == threading.get_ident():
                            continue
                        locations = []
                        for _ in range(24):
                            if frame is None:
                                break
                            locations.append(f"{Path(frame.f_code.co_filename).name}:{frame.f_lineno}:{frame.f_code.co_name}")
                            frame = frame.f_back
                        stacks[str(ident)] = {"name": names.get(ident, "native"), "stack": locations}
                    operations = {str(k): [{"name": n, "ms": round((now - t) * 1000, 1)}
                                           for n, t in list(v)] for k, v in list(self.active.items()) if v}
                    write({"event": "ui_stall", "gap_ms": round(lag * 1000, 1),
                           "operations": operations, "stacks": stacks})
                if now - last_summary >= 10:
                    cpu = time.process_time()
                    write({"event": "sample", "cpu_percent": round(100 * (cpu - last_cpu) / (now - last_summary), 1)})
                    last_summary, last_cpu = now, cpu
            while self.events:
                write(self.events.popleft())
            write({"event": "stop"})
        finally:
            handler.close()


def install(app, directory):
    global _monitor
    if os.environ.get("PLAYER_PERF_LOG", "1") == "0":
        return None
    _monitor = Monitor(app, directory)
    return _monitor
