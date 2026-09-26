#!/usr/bin/env python3
"""Reload the visualizer surface with synthetic frames, offscreen and no audio."""
import os
from pathlib import Path
import sys
import tempfile
import time

assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
scratch = tempfile.TemporaryDirectory(prefix='visualizer-tabs-')
for key in ('CONFIG', 'CACHE', 'DATA', 'STATE', 'RUNTIME'):
    path = Path(scratch.name)/key
    path.mkdir(mode=0o700)
    os.environ['XDG_RUNTIME_DIR' if key == 'RUNTIME' else 'XDG_'+key+'_HOME'] = str(path)
os.environ.update(QT_QUICK_CONTROLS_STYLE='Basic', QT_STYLE_OVERRIDE='Fusion',
                  DBUS_SESSION_BUS_ADDRESS='unix:path='+scratch.name+'/no-bus')
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from visualizer import Visualizer, register

app = QApplication([])
assert app.platformName() == 'offscreen'
register()
errors = []


def report_exception(kind, value, traceback):
    errors.append(str(value))
    sys.__excepthook__(kind, value, traceback)


sys.excepthook = report_exception
worker = """import json,signal,struct,sys,time
# Keep teardown pending long enough to exercise a quick return to the tab.
def stop(*args):
 time.sleep(.1)
 sys.exit(0)
signal.signal(signal.SIGTERM,stop)
frame=b'F'+struct.pack('!III',12,1,1)+bytes([255,0,0,255])
while True:
 sys.stdout.buffer.write(frame);sys.stdout.buffer.flush()
 while json.loads(sys.stdin.buffer.readline()).get('op')!='ack':pass
 time.sleep(.01)
"""
body = """
    width: 320; height: 240
    property bool selected: false
    Loader {
        anchors.fill: parent
        active: selected
        sourceComponent: Component { VisualizerSurface { source: Visualizer } }
    }
    onSelectedChanged: Visualizer.setShown(selected)
"""


def wait_for(predicate):
    deadline = time.monotonic()+5
    while not predicate() and not errors and time.monotonic() < deadline:
        QTest.qWait(5)
    assert not errors, errors
    assert predicate(), 'tab lifecycle timeout'


for native in (False, True):
    visual = Visualizer('synthetic-tabs', app)
    visual.worker_command = [sys.executable, '-c', worker]
    if native:
        window = QQuickWidget()
        window.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        engine = window.engine()
    else:
        engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('Visualizer', visual)
    qml = ('import QtQuick\nimport Player.Visualizer 1.0\n'
           + ('Item {' if native else 'Window { visible: true;') + body + '}').encode()
    if native:
        component = QQmlComponent(engine)
        component.setData(qml, QUrl())
        root = component.create()
        assert root, component.errorString()
        window.setContent(QUrl(), component, root)
    else:
        engine.loadData(qml)
        root = window = engine.rootObjects()[0]
    window.resize(320, 240)
    window.show()
    visual.bind_window(window)
    received = []
    visual.frame.connect(lambda image: received.append(image))

    def red_frame():
        image = window.grabFramebuffer() if native else window.grabWindow()
        return not image.isNull() and image.pixelColor(100, 100).name() == '#ff0000'

    try:
        for delay in (150, 0, 150, 0, 150):
            count = len(received)
            generation = visual.generation
            root.setProperty('selected', True)
            wait_for(lambda: visual.generation > generation and len(received) > count)
            wait_for(red_frame)
            root.setProperty('selected', False)
            assert visual.process.stopping
            QTest.qWait(delay)
            # Keep the original wrapper: reacquiring it hides the invalidation
            # that otherwise prevents Visualizer.shown() from restarting.
            assert window.isVisible()
            if delay:
                wait_for(lambda: visual.process is None)
        wait_for(lambda: visual.process is None)
        assert not errors, errors
        print('PASS repeated tab return, pending shutdown, and rendered pixels:',
              'Plasma QQuickWidget' if native else 'Hyprland QQuickWindow')
    finally:
        visual.shutdown()
        window.close()
        if native:
            window.deleteLater()
        else:
            engine.deleteLater()
        QTest.qWait(20)
        visual.deleteLater()
scratch.cleanup()
