#!/usr/bin/env python3
"""Offscreen presentation/backpressure at full HD; synthetic pixels, no audio."""
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
scratch = tempfile.TemporaryDirectory(prefix='visualizer-presentation-')
for key in ('CONFIG','CACHE','DATA','STATE','RUNTIME'):
    path = Path(scratch.name)/key
    path.mkdir(mode=0o700)
    os.environ['XDG_RUNTIME_DIR' if key=='RUNTIME' else 'XDG_'+key+'_HOME'] = str(path)
os.environ.update(QT_QUICK_CONTROLS_STYLE='Basic', QT_STYLE_OVERRIDE='Fusion',
                  DBUS_SESSION_BUS_ADDRESS='unix:path='+scratch.name+'/no-bus')
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from visualizer import Visualizer, VisualizerSurface, register

app = QApplication([])
register()
worker = """import json,mmap,os,struct,sys,time
file=open(os.environ['GF_PLAYER_FRAME_FILE'],'r+b')
pixels=mmap.mmap(file.fileno(),1920*1080*4)
pixels[:]=bytes([255,0,0,255])*(1920*540)+bytes([0,0,255,255])*(1920*540)
frame=b'M'+struct.pack('!III',8,1920,1080)
deadline=time.monotonic()
for i in range(120):
 time.sleep(max(0,deadline-time.monotonic()))
 # Mutate shared storage every frame, only after the previous ACK.
 pixels[0]=i
 sys.stdout.buffer.write(frame);sys.stdout.buffer.flush()
 while json.loads(sys.stdin.buffer.readline()).get('op')!='ack': pass
 deadline=max(deadline+1/60,time.monotonic())
time.sleep(60)
"""
def wait_for(predicate):
    end=time.monotonic()+10
    while not predicate() and time.monotonic()<end:
        QTest.qWait(2)
    assert predicate(), 'presentation timeout'

for native in (False,True):
    visual=Visualizer('synthetic')
    visual.closed=True  # explicit fixture lifetime, never auto-restart
    visual.worker_command=[sys.executable,'-c',worker]
    if native:
        window=QQuickWidget()
        window.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        window.rootContext().setContextProperty('Visualizer',visual)
        component=QQmlComponent(window.engine())
        component.setData(b'import QtQuick\nimport Player.Visualizer 1.0\nVisualizerSurface { source: Visualizer }',QUrl())
        surface=component.create()
        assert surface,component.errorString()
        window.setContent(QUrl(),component,surface)
    else:
        window=QQuickWindow()
        surface=VisualizerSurface(window.contentItem())
        surface.source=visual
        surface.setWidth(2560);surface.setHeight(1440)
    window.resize(2560,1440)
    received=[];consumed=[]
    visual.frame.connect(lambda image:received.append((time.monotonic(),image.pixelColor(0,0).red())))
    surface.consumed.connect(lambda _:consumed.append(time.monotonic()))
    try:
        visual.start()
        wait_for(lambda:len(received)==1)
        descriptor=visual.process.frame_fd
        visual.acknowledge(visual.generation-1)
        QTest.qWait(120)
        assert len(received)==1 and visual.frame_pending,'ACK released before presentation'
        window.show()
        cpu=time.process_time()
        wait_for(lambda:len(consumed)==120)
        cost=time.process_time()-cpu
        assert [red for _,red in received]==list(range(120)), 'shared frame overwritten or skipped'
        assert len(consumed)==len(received), 'frame replaced before scene-graph upload'
        output=window.grabFramebuffer() if native else window.grabWindow()
        assert not output.isNull()
        assert output.pixelColor(20,20).blue()==255,'upside-down texture'
        assert output.pixelColor(20,output.height()-20).red()==255
        gaps=[(b-a)*1000 for a,b in zip(consumed[5:],consumed[6:])]
        print('PASS', 'Plasma QQuickWidget' if native else 'QQuickWindow',
              '120/120 frames; CPU',round(cost,3),'s; gap median/p95/max',
              *(round(x,2) for x in (statistics.median(gaps),sorted(gaps)[int(.95*len(gaps))],max(gaps))))
        # Resize without a new image must preserve the texture and not ACK twice.
        count=len(consumed)
        window.resize(1280,720)
        if not native: surface.setWidth(1280);surface.setHeight(720)
        QTest.qWait(30)
        assert len(consumed)==count
    finally:
        visual.shutdown()
        window.close()
        window.deleteLater()
        QTest.qWait(20)
    try: os.fstat(descriptor)
    except OSError: pass
    else: raise AssertionError('shared frame descriptor leaked')
failed=Visualizer('missing-renderer')
failed.closed=True
failed.worker_command=[str(Path(scratch.name)/'no-renderer')]
failed.start()
wait_for(lambda:failed.process is None)
assert not failed.frame_pending
for descriptor in Path('/proc/self/fd').iterdir():
    try: target=os.readlink(descriptor)
    except FileNotFoundError: continue
    assert 'memfd:player-visualizer' not in target, 'failed-start frame descriptor leaked'
print('PASS failed renderer startup releases shared frame storage')
scratch.cleanup()
