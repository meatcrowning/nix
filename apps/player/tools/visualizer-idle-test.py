#!/usr/bin/env python3
"""Offscreen focus/playback lifecycle with a disposable, audio-free worker."""
import os
from pathlib import Path
import sys

assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtTest import QTest
from visualizer import Visualizer

app = QApplication([])
assert app.platformName() == 'offscreen'

# Control focus independently of the offscreen platform's activation policy.
class QuickWindow(QQuickWindow):
    focused = False
    def isActive(self): return self.focused

class WidgetWindow(QMainWindow):
    focused = False
    def isActiveWindow(self): return self.focused

for window_type in (QuickWindow, WidgetWindow):
    window = window_type()
    visual = Visualizer('isolated-idle')
    visual.worker_command = [sys.executable, '-c', 'import time; time.sleep(60)']
    visual.bind_window(window)

    def running(expected):
        for _ in range(100):
            QTest.qWait(10)
            process = visual.process
            if (process is not None and bool(process.processId())
                    and not getattr(process, 'stopping', False)) == expected:
                if expected or process is None:
                    return
        raise AssertionError((window_type.__name__, expected, visual.state))

    def focus(active):
        window.focused = active
        kind = QEvent.Type.WindowActivate if active else QEvent.Type.WindowDeactivate
        app.sendEvent(window, QEvent(kind))

    try:
        window.show()
        visual.setShown(True)
        running(False)
        focus(True)
        running(True)
        pid = visual.process.processId()
        focus(False)
        running(False)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError('idle worker survived')
        visual.setPlaying(True)
        running(True)
        focus(True)
        running(True)
        visual.setPlaying(False)
        running(True)
        focus(False)
        running(False)
        window.showMinimized()
        visual.setPlaying(True)
        running(False)
        focus(True)
        running(False)
        focus(False)
        window.showNormal()
        running(True)
        window.hide()
        running(False)
        window.show()
        running(True)
        visual.setShown(False)
        running(False)
        visual.setPlaying(False)
        focus(True)
        running(False)
        visual.setShown(True)
        running(True)
        # Playback resumes before asynchronous process teardown completes.
        focus(False)
        QTest.qWait(1)
        visual.setPlaying(True)
        running(True)
    finally:
        visual.shutdown()
        window.close()
    assert visual.process is None
    print('PASS focus, playback, minimize, hide, page and teardown:', window_type.__name__)
