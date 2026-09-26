#!/usr/bin/env python3
"""Offscreen full-HD presentation with delayed repaints; no audio."""
import os
from collections import deque
from types import SimpleNamespace
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
import perftrace

app = QApplication([])
register()
# Exercise the real per-frame summaries without creating a logging thread.
perftrace._monitor=SimpleNamespace(visualizer_frames={},events=deque(maxlen=20))
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
    surface.consumed.connect(lambda _:consumed.append((time.monotonic(),surface._image.pixelColor(0,0).red())))
    try:
        visual.start()
        wait_for(lambda:len(received)==1)
        descriptor=visual.process.frame_fd
        # Withhold all repaint opportunities while leaving the GUI event
        # loop responsive. The old paint/ACK coupling stopped at one frame.
        QTest.qWait(140)
        assert len(received)>=6 and not consumed,'producer waits for a repaint'
        newest=received[-1][1]
        window.show()
        cpu=time.process_time()
        wait_for(lambda:len(consumed)>0)
        assert consumed[0][1]>=newest,'replayed stale frame after repaint resumed'
        wait_for(lambda:len(received)>=30)
        window.hide()
        before=len(received)
        QTest.qWait(140)
        assert len(received)>=before+5,'missed paints stalled production'
        newest=received[-1][1]
        count=len(consumed)
        window.show()
        wait_for(lambda:len(consumed)>count)
        assert consumed[count][1]>=newest,'queued old frames during paint stall'
        wait_for(lambda:len(received)==120 and consumed[-1][1]==119)
        cost=time.process_time()-cpu
        assert [red for _,red in received]==list(range(120)), 'shared frame overwritten or skipped'
        output=window.grabFramebuffer() if native else window.grabWindow()
        assert not output.isNull()
        assert output.pixelColor(20,20).blue()==255,'upside-down texture'
        assert output.pixelColor(20,output.height()-20).red()==255
        gaps=[(b[0]-a[0])*1000 for a,b in zip(received[5:],received[6:])]
        print('PASS', 'Plasma QQuickWidget' if native else 'QQuickWindow',
              '120/120 received;',len(consumed),'uploads; CPU',round(cost,3),'s; receipt gap median/p95/max',
              *(round(x,2) for x in (statistics.median(gaps),sorted(gaps)[int(.95*len(gaps))],max(gaps))))
        # Resize without a new image must preserve the texture without a new upload.
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
for descriptor in Path('/proc/self/fd').iterdir():
    try: target=os.readlink(descriptor)
    except FileNotFoundError: continue
    assert 'memfd:player-visualizer' not in target, 'failed-start frame descriptor leaked'
print('PASS failed renderer startup releases shared frame storage')
events=list(perftrace._monitor.events)
assert {event['stage'] for event in events}=={'received','uploaded'}
assert all(event['fps']>0 and event['max_ms']>=event['p95_ms']>=event['median_ms'] for event in events)
assert any(event['stage']=='uploaded' and event['max_ms']>=100 for event in events), events
perftrace._monitor=None
print('PASS frame diagnostics distinguish arrival from delayed repaint')
scratch.cleanup()
