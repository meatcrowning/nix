#!/usr/bin/env python3
"""Native transport/frame pacing probe; run through visualizer-cadence-test.sh.

No mpv or audio: a synthetic worker exercises the real frame transport. Compare
idle, independent seek updates, synchronized seek updates, then idle again.
"""
import os, sys, time
from pathlib import Path
assert os.environ['QT_QPA_PLATFORM'] == 'wayland'
assert os.environ['WAYLAND_DISPLAY'] == str(Path(os.environ['XDG_RUNTIME_DIR'])/'cadence-test')
assert Path(os.environ['XDG_RUNTIME_DIR']).parent.name.startswith('player-cadence.')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QUrl, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QToolBar
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuickWidgets import QQuickWidget
from visualizer import Visualizer, register
app=QApplication([]);register()
assert app.style().objectName().lower()=='oxygen', 'this probe requires the Oxygen style'
visual=Visualizer('synthetic'); visual.closed=True
worker='''import json,mmap,os,struct,sys,time
f=open(os.environ['GF_PLAYER_FRAME_FILE'],'r+b');p=mmap.mmap(f.fileno(),1920*1080*4)
p[:]=bytes([80,0,180,255])*(1920*1080)
deadline=time.monotonic()
while True:
 time.sleep(max(0,deadline-time.monotonic()))
 sys.stdout.buffer.write(b'M'+struct.pack('!III',8,1920,1080));sys.stdout.buffer.flush()
 while json.loads(sys.stdin.buffer.readline()).get('op')!='ack': pass
 deadline=max(deadline+1/60,time.monotonic())
'''
visual.worker_command=[sys.executable,'-c',worker]
window=QMainWindow();view=QQuickWidget();view.setResizeMode(QQuickWidget.SizeRootObjectToView)
view.rootContext().setContextProperty('Visualizer',visual)
component=QQmlComponent(view.engine());component.setData(b'import QtQuick\nimport Player.Visualizer 1.0\nVisualizerSurface { source: Visualizer }',QUrl())
surface=component.create();assert surface,component.errorString()
view.setContent(QUrl(),component,surface);window.setCentralWidget(view)
bar=QToolBar();window.addToolBar(Qt.BottomToolBarArea,bar)
from transport import TransportSeek
from PySide6.QtCore import QObject, Signal
class Player(QObject):
 positionChanged=Signal();durationChanged=Signal();indexChanged=Signal()
 duration=300;index=0;position=0
 def seekFrac(self, frac): self.position=frac*self.duration;self.positionChanged.emit()
player=Player();seek=TransportSeek(player, render_window=view.quickWindow());bar.addWidget(seek)
window.resize(1600,1000)
records={'received':[], 'uploaded':[]}
visual.frame.connect(lambda _:records['received'].append(time.monotonic()))
surface.consumed.connect(lambda _:records['uploaded'].append(time.monotonic()))
phase=0
results={}
updates=QTimer();updates.setInterval(200)
def update():
 player.position+=.2;player.positionChanged.emit()
updates.timeout.connect(update)
def report():
 global phase
 for stage, timestamps in records.items():
  gaps=[(b-a)*1000 for a,b in zip(timestamps,timestamps[1:])]
  fps=len(gaps)/(timestamps[-1]-timestamps[0])
  p95=sorted(gaps)[int(.95*len(gaps))]
  results[phase,stage]=(fps,p95)
  print(phase,stage,round(fps,2),'fps; gap p95/max',round(p95,2),round(max(gaps),2),'ms',flush=True)
  timestamps.clear()
 phase+=1
 if phase==1: updates.start()
 if phase==2: seek.set_visualizer_active(True)
 if phase==3: updates.stop()
 if phase==4: app.quit()
clock=QTimer();clock.setInterval(5000);clock.timeout.connect(report)
QTimer.singleShot(30000, app.quit)
window.show();visual.start();clock.start()
try:
 app.exec()
finally:
 visual.shutdown()
 surface.source=None
 window.close()
assert results[2,'uploaded'][0]>=58, results
assert results[2,'uploaded'][1]<25, results
print('PASS Oxygen playback updates preserve visualizer cadence')
