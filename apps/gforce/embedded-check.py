"""Real surfaceless renderer with synthetic PCM, isolated settings and presets."""
import math
import os
import json
import select
import signal
import struct
import subprocess
import sys
from pathlib import Path
import tempfile
import time

assert os.environ.get('QT_QPA_PLATFORM')=='offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
from embedded_worker import Engine

with tempfile.TemporaryDirectory(prefix='gforce-embedded-') as directory:
    root=Path(directory)
    os.environ['XDG_CONFIG_HOME']=str(root/'config')
    os.environ['GF_SHARED_DIALS_DIR']=str(root/'shared')
    os.environ['GF_ENGINE_STATE_DIR']=str(root/'engine')
    (root/'engine').mkdir()
    class Audio:
        def sample(self,now,hold): return [.2*math.sin(i*.13+now) for i in range(550)]
    engine=Engine(os.environ['GF_RENDERER_PATH'])
    try:
        started=time.monotonic()
        for _ in range(30): image=engine.frame(Audio())
        print('PASS real renderer:',round((time.monotonic()-started)*1000/30,1),'ms/frame at 640×360')
        assert len(image)==8+640*360*4
        assert len({image[i:i+3] for i in range(8,len(image),40)})>1,'blank frame'
        for name,value in [('persist',40),('fps',60),('rate',2),('grid',320),('resolution',.5),('hitHold',80)]:
            engine.command({'op':'dial','name':name,'value':value})
        assert abs(engine.lib.gf_get(b'persist')-.5**(1/40))<1e-6
        engine.command({'op':'key','key':' '})
        assert engine.snapshot('')['paused']
        engine.command({'op':'savePreset'})
        assert len(engine.presets)==1
        engine.command({'op':'preset','index':0})
        engine.command({'op':'compare'})
        assert engine.comparison is not None
        engine.command({'op':'compare'})
        assert engine.values['fps']==60 and engine.values['persist']==40
        engine.save()
        assert (root/'config/gforce-vis/dials.json').exists()
        engine.command({'op':'deletePreset','index':0})
        assert not engine.presets
        print('PASS dial units, keys, saved looks, comparison, persistence')
    finally:engine.close()

    # Exercise the exact process protocol with synthetic audio; even a mistaken
    # capture call can reach only a nonexistent server, never the live graph.
    env=dict(os.environ, PIPEWIRE_REMOTE="/dev/null", PULSE_SERVER="unix:"+str(root/"no-pulse"))
    code="""import sys, time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import embedded_worker as worker
class Audio:
    status='synthetic'
    def __init__(self,*args): pass
    def sample(self,now,hold): return [0.1]*550
    def close(self): pass
worker.PlayerAudio=Audio
worker.main()
"""
    with (root/'worker.log').open('w+') as log:
        proc=subprocess.Popen([sys.executable,'-c',code,str(Path(__file__).resolve().parent)],
            env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,start_new_session=True)
        def command(msg):
            proc.stdin.write(json.dumps(msg).encode()+b'\n');proc.stdin.flush()
        def read_exact(n):
            data=bytearray();deadline=time.monotonic()+10
            while len(data)<n:
                assert time.monotonic()<deadline,'protocol timeout'
                if not select.select([proc.stdout],[],[],.1)[0]:continue
                chunk=os.read(proc.stdout.fileno(),n-len(data))
                assert chunk,'worker stopped unexpectedly'
                data.extend(chunk)
            return bytes(data)
        def message():
            header=read_exact(5)
            return header[:1],read_exact(struct.unpack('!I',header[1:])[0])
        try:
            command({'op':'size','width':320,'height':180})
            while True:
                kind,data=message()
                if kind==b'F':break
                assert kind==b'J' and json.loads(data)['ready']
            assert struct.unpack('!II',data[:8])==(320,180)
            assert len(data)==8+320*180*4
            # No ACK: no second frame is allowed to accumulate.
            deadline=time.monotonic()+.3
            while time.monotonic()<deadline:
                if select.select([proc.stdout],[],[],.05)[0]:
                    kind,_=message();assert kind!=b'F'
            command({'op':'ack'})
            while message()[0]!=b'F':pass
            print('PASS framed process output, resize and bounded one-frame backpressure')
        finally:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait();raise
            if proc.returncode:
                log.seek(0);print(log.read())
            assert proc.returncode==0,proc.returncode
