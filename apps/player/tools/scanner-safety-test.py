#!/usr/bin/env python3
"""Scratch-only scanner traversal, completion and automatic import regressions."""
import os
import runpy
import sys
import tempfile
import time
import threading
from pathlib import Path
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ.pop('WAYLAND_DISPLAY', None)
os.environ.pop('DISPLAY', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as P
from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
assert app.platformName() == 'offscreen'
track = runpy.run_path(str(Path(__file__).with_name('scanner-lock-test.py')))['track']
with tempfile.TemporaryDirectory(prefix='player-scan-safe-') as td:
    root = Path(td)
    P.DATA, P.DB_PATH, P.LIBRARY_ROOT = root, root / 'db', root
    P.read_tags = lambda path: track(Path(path))
    (root / 'nested').mkdir()
    survivor, hidden = root / 'a.flac', root / 'nested/b.flac'
    survivor.touch(); hidden.touch()
    con = P.open_db()
    scan = P.Scanner()
    summaries, done = [], []
    scan.summary.connect(summaries.append)
    scan.done.connect(lambda: done.append(True))
    scan._run(con, time.time())
    scandir = os.scandir
    def unreadable(path):
        if Path(path) == hidden.parent:
            raise PermissionError('fixture unreadable')
        return scandir(path)
    with patch.object(P.os, 'scandir', unreadable):
        scan._run(con, time.time())
    assert con.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 2
    assert summaries[-1]['incomplete'] and summaries[-1]['pruned'] == 0
    # Cancellation after a tag read must not prune a now-missing known file or
    # commit the parsed-but-not-landed row.
    entered, release = threading.Event(), threading.Event()
    extra = root / 'new.flac'
    extra.touch()
    hidden.unlink()
    def slow_tags(path):
        entered.set()
        assert release.wait(2)
        return track(Path(path))
    with patch.object(P, 'read_tags', slow_tags):
        cancelled = P.Scanner()
        cancelled.start()
        assert entered.wait(2)
        cancelled.requestInterruption()
        release.set()
        assert cancelled.wait(2000)
    assert con.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 2
    assert con.execute('SELECT 1 FROM tracks WHERE path=?', (str(hidden),)).fetchone()
    extra.unlink()
    scan._run(con, time.time())
    assert summaries[-1]['pruned'] == 1
    survivor.unlink()
    scan._run(con, time.time())
    assert summaries[-1]['pruned'] == 0  # empty mount safeguard
    with patch.object(P, 'open_db', side_effect=RuntimeError('fixture open failed')):
        scan.run()
    assert done == [True] and summaries[-1]['error'] == 'fixture open failed'
    con.close()

    class Notices:
        def __init__(self): self.errors = []
        def emit(self, message): self.errors.append(message)
    class Library:
        def __init__(self): self.scans = 0; self.writeFailed = Notices()
        def rescan(self): self.scans += 1
    auto = P.AutoScanner.__new__(P.AutoScanner)
    QObject.__init__(auto)
    auto._library = Library()
    auto._import_pending = False
    auto._import_timer = QTimer(auto)
    auto._import_timer.setSingleShot(True)
    proc = QProcess(auto)
    auto._proc = proc
    auto._run_import()
    assert auto._import_pending
    auto._on_import_done(0, QProcess.NormalExit)
    assert auto._proc is None and auto._import_timer.isActive()
    assert auto._library.scans == 1
    auto._import_timer.stop()
    # A real failed-start signal must release the busy flag and permit retry.
    with patch.object(P.sys, 'executable', str(root / 'missing-python')):
        auto._run_import()
        deadline = time.monotonic() + 2
        while auto._proc is not None and time.monotonic() < deadline:
            app.processEvents()
    assert auto._proc is None and auto._library.writeFailed.errors
    auto._import_timer.stop()
    worker = P.WatchDirectories([str(root)])
    worker.run()
    assert str(root / 'nested') in worker.paths

    class FakeScanner(QObject):
        progress = Signal(int, int)
        batch = Signal()
        summary = Signal('QVariantMap')
        finished = Signal()
        def __init__(self, parent=None): super().__init__(parent); self.running = False
        def start(self): self.running = True
        def isRunning(self): return self.running
    library = P.Library.__new__(P.Library)
    QObject.__init__(library)
    library._scanner = None
    library._scan_pending = False
    states = []
    library.scanRunning.connect(states.append)
    with patch.object(P, 'Scanner', FakeScanner):
        library.rescan()
        first = library._scanner
        library.rescan(); library.rescan()
        assert library._scanner is first and library._scan_pending
        first.running = False
        first.finished.emit()
        assert library._scanner is not first and not library._scan_pending
        library._scanner.running = False
        library._scanner.finished.emit()
    assert states == [True, True, False]
print('scanner safety test: ok')
