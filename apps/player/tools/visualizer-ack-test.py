#!/usr/bin/env python3
"""A queued ACK must leave before the GUI enters its next display wait."""
import os
from pathlib import Path
import statistics
import sys
import time

assert os.environ.get('QT_QPA_PLATFORM')=='offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QTimer
from visualizer import Visualizer

app=QCoreApplication([])
visual=Visualizer('synthetic-ack')
visual.closed=True
worker="""import json,mmap,os,struct,sys,time
file=open(os.environ['GF_PLAYER_FRAME_FILE'],'r+b')
pixels=mmap.mmap(file.fileno(),1920*1080*4)
pixels[:4]=bytes([255,0,0,255])
frame=b'M'+struct.pack('!III',8,1,1)
delays=[]
for i in range(30):
 started=time.monotonic()
 sys.stdout.buffer.write(frame);sys.stdout.buffer.flush()
 while json.loads(sys.stdin.buffer.readline()).get('op')!='ack':pass
 delays.append((time.monotonic()-started)*1000)
 # Separate the event-loop flush from the next frame's arrival.
 time.sleep(.03)
data=json.dumps({'ackDelays':delays}).encode()
sys.stdout.buffer.write(b'J'+struct.pack('!I',len(data))+data)
sys.stdout.buffer.flush()
time.sleep(60)
"""
visual.worker_command=[sys.executable,'-c',worker]
# Model the display wait observed immediately after readyRead in the live
# trace. This stalls only our isolated event loop, never the desktop.
visual.frame.connect(lambda _:time.sleep(.020))
visual.changed.connect(lambda:app.quit() if 'ackDelays' in visual.state else None)
QTimer.singleShot(10000,app.quit)
try:
    visual.start()
    app.exec()
    delays=visual.state.get('ackDelays',[])
    assert len(delays)==30,visual.state
    median=statistics.median(delays)
    print('ACK delivery median/max ms:',round(median,3),round(max(delays),3))
    assert median<5, 'ACK waited for the GUI display wait to end'
finally:
    visual.shutdown()
print('PASS acknowledgement leaves before the GUI display wait')
