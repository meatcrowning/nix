"""Real per-stream capture on private PipeWire/WirePlumber with no device monitors."""
from array import array
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from player_audio import PlayerAudio, props

assert os.environ.get('QT_QPA_PLATFORM')=='offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
children=[]
tap=None
with tempfile.TemporaryDirectory(prefix='player-audio-check-') as directory:
    root=Path(directory)
    for name in ('run','config','state','data','cache'): (root/name).mkdir()
    (root/'run').chmod(0o700)
    os.environ.update(XDG_RUNTIME_DIR=str(root/'run'), XDG_CONFIG_HOME=str(root/'config'),
        XDG_STATE_HOME=str(root/'state'),XDG_DATA_HOME=str(root/'data'),XDG_CACHE_HOME=str(root/'cache'),
        PIPEWIRE_RUNTIME_DIR=str(root/'run'),PIPEWIRE_CORE='visualizer-test',PIPEWIRE_REMOTE='visualizer-test',
        PULSE_SERVER='unix:'+str(root/'no-pulse'),DBUS_SESSION_BUS_ADDRESS='unix:path='+str(root/'bus'))
    pw=root/'config/pipewire/pipewire.conf.d';pw.mkdir(parents=True)
    (pw/'99-test.conf').write_text('''context.objects = [ { factory = adapter args = {
        factory.name = support.null-audio-sink node.name = visualizer-test-sink
        media.class = Audio/Sink audio.position = [ FL FR ] object.linger = true
    } } ]\n''')
    wp=root/'config/wireplumber/wireplumber.conf.d';wp.mkdir(parents=True)
    monitors=['monitor.alsa','monitor.alsa.reserve-device','monitor.alsa-midi','monitor.bluez',
              'monitor.bluez-midi','monitor.libcamera','monitor.v4l2']
    if Path('/usr/share/wireplumber/wireplumber.conf.d/99-asahi.conf').exists():
        monitors+=['custom.asahi','node.software-dsp']
    (wp/'99-test.conf').write_text('wireplumber.profiles = { main = {\n'+
        '\n'.join(f'{m} = disabled' for m in monitors)+'\n} }\n')
    logs=(root/'daemons.log').open('w+')
    def spawn(args):
        process=subprocess.Popen(args,stdout=logs,stderr=logs)
        children.append(process);return process
    def graph(): return json.loads(subprocess.check_output(['pw-dump'],timeout=2))
    def wait_for(fn,timeout=5):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if fn(): return
            time.sleep(.1)
        raise AssertionError('timed out; '+(tap.status if tap else 'starting private server'))
    def play(name,freq,amplitude):
        path=root/(name+'.raw')
        block=array('f',(amplitude*math.sin(2*math.pi*freq*(i//2)/22050) for i in range(22050*2)))
        path.write_bytes(block.tobytes()*40)
        return spawn(['pw-play','--target=visualizer-test-sink','--raw','--format=f32','--rate=22050',
                      '--channels=2','--properties='+json.dumps({'node.name':name}),str(path)])
    try:
        spawn(['dbus-daemon','--session','--nofork','--address='+os.environ['DBUS_SESSION_BUS_ADDRESS']])
        spawn(['pipewire'])
        wait_for(lambda:(root/'run/visualizer-test').is_socket())
        spawn(['wireplumber'])
        time.sleep(2)
        assert not any(props(o).get('device.api') in ('alsa','bluez5') for o in graph()),'device monitor escaped'
        music=play('player-test',330,.2)
        other=play('desktop-noise',1300,.8)
        tap=PlayerAudio('player-test')
        wait_for(lambda:max(map(abs,tap.sample(time.monotonic(),0)))>.05)
        samples=tap.sample(time.monotonic(),0)
        def power(freq):
            return abs(sum(v*complex(math.cos(2*math.pi*freq*i/22050),math.sin(2*math.pi*freq*i/22050))
                           for i,v in enumerate(samples)))
        assert power(330)>20*power(1300),(power(330),power(1300))
        g=graph()
        rec=next(o['id'] for o in g if props(o).get('node.name')==tap.recorder_name)
        links=[o['info'] for o in g if o['type'].endswith(':Link') and o['info'].get('input-node-id')==rec]
        own=next(o['id'] for o in g if props(o).get('node.name')=='player-test')
        assert len(links)==2 and all(o['output-node-id']==own for o in links),links
        print('PASS captures only Player, with direct upstream links; unrelated tone excluded')
        original_dump = subprocess.check_output
        def slow_dump(*args, **kwargs):
            if threading.current_thread() is not threading.main_thread() and args[0] == ['pw-dump']:
                time.sleep(.3)
            return original_dump(*args, **kwargs)
        subprocess.check_output = slow_dump
        try:
            ages = []
            updates = set()
            deadline = time.monotonic()+2.8
            while time.monotonic() < deadline:
                with tap.lock:
                    ages.append(time.monotonic()-tap.last_audio)
                    updates.add(tap.last_audio)
                time.sleep(.01)
            print('PCM updates observed during 2.8s:',len(updates))
            assert len(updates)>=180, 'audio refresh is too slow for a 60 Hz visualizer'
            assert max(ages) < .15, f'graph polling stalled capture for {max(ages):.3f}s'
            print('PASS slow graph inspection leaves PCM capture uninterrupted')
        finally:
            subprocess.check_output = original_dump
        music.terminate();music.wait()
        wait_for(lambda:all(v==0 for v in tap.sample(time.monotonic(),0)))
        assert other.poll() is None
        print('PASS missing Player yields silence while other desktop audio continues')
        music=play('player-test',330,.2)
        wait_for(lambda:max(map(abs,tap.sample(time.monotonic(),0)))>.05)
        print('PASS stream recreation reconnects only to Player')
        tap.close()
        wait_for(lambda:not any(props(o).get('node.name')==tap.recorder_name for o in graph()))
        print('PASS shutdown removes recorder and tap links')
    except BaseException:
        logs.flush();logs.seek(0);print(logs.read()[-4000:]);raise
    finally:
        if tap:tap.close()
        for child in reversed(children):
            if child.poll() is None:child.terminate()
        for child in reversed(children):
            try:child.wait(timeout=3)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        logs.close()
