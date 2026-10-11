"""Real Rhythmbox close/reopen/quit, private display/profile/bus/null audio."""
assert os.environ['HOME'] == '/home/test' and Path('/work/inside.sh').is_file()
import socket
import wave

inside = r'''
import ctypes as c, json, os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, '/runner')
import isolated as m
server = subprocess.Popen([m.CONFIG['xvfb'], ':94', '-screen', '0', '800x600x24', '-nolisten', 'tcp', '-ac', '-noreset'])
worker = None
try:
    for _ in range(100):
        if Path('/tmp/.X11-unix/X94').exists(): break
        assert server.poll() is None
        time.sleep(.05)
    else: raise RuntimeError('private display not ready')
    os.environ['DISPLAY'] = ':94'
    worker = subprocess.Popen([m.CONFIG['python'], '/runner/isolated.py', 'worker', 'rhythmbox'])
    tools = Path('/transport/tools').read_text()
    def visible():
        return subprocess.run([tools+'/bin/xdotool','search','--onlyvisible','--class','^Rhythmbox$'],
                              capture_output=True,text=True).stdout.splitlines()
    for _ in range(300):
        windows = visible()
        if windows: break
        assert worker.poll() is None
        time.sleep(.1)
    else: raise RuntimeError('Rhythmbox did not map')
    window = int(windows[-1])
    pid = subprocess.check_output([tools+'/bin/xdotool','getwindowpid',str(window)],text=True).strip()
    env = dict(item.split('=',1) for item in Path('/proc/'+pid+'/environ').read_bytes().decode().split('\0') if '=' in item)
    subprocess.run(['/usr/bin/rhythmbox-client','--no-start','--play-uri','file:///transport/silence.wav'],env=env,check=True,timeout=15)
    for _ in range(100):
        status=subprocess.check_output(['/usr/bin/gdbus','call','--session','--dest','org.mpris.MediaPlayer2.rhythmbox',
            '--object-path','/org/mpris/MediaPlayer2','--method','org.freedesktop.DBus.Properties.Get',
            'org.mpris.MediaPlayer2.Player','PlaybackStatus'],env=env,text=True)
        if 'Playing' in status: break
        time.sleep(.05)
    else: raise RuntimeError('private null-sink playback did not start')
    Path('/transport/ready').write_text(pid)
    while not Path('/transport/hide').exists(): time.sleep(.05)
    library = next(Path(p)/'libX11.so.6' for p in m.CONFIG['modernLibraries'].split(':') if (Path(p)/'libX11.so.6').exists())
    x=c.CDLL(str(library))
    class Message(c.Structure):
        _fields_=[('type',c.c_int),('serial',c.c_ulong),('send_event',c.c_int),('display',c.c_void_p),('window',c.c_ulong),('message_type',c.c_ulong),('format',c.c_int),('data',c.c_long*5)]
    class Event(c.Union):
        _fields_=[('message',Message),('padding',c.c_long*24)]
    x.XOpenDisplay.argtypes=[c.c_char_p]; x.XOpenDisplay.restype=c.c_void_p
    x.XInternAtom.argtypes=[c.c_void_p,c.c_char_p,c.c_int]; x.XInternAtom.restype=c.c_ulong
    x.XSendEvent.argtypes=[c.c_void_p,c.c_ulong,c.c_int,c.c_long,c.POINTER(Event)]
    x.XCloseDisplay.argtypes=[c.c_void_p]
    display=x.XOpenDisplay(b':94'); assert display
    event=Event()
    event.message=Message(33,0,1,display,window,x.XInternAtom(display,b'WM_PROTOCOLS',0),32,(c.c_long*5)(x.XInternAtom(display,b'WM_DELETE_WINDOW',0),0,0,0,0))
    assert x.XSendEvent(display,window,0,0,c.byref(event))
    x.XCloseDisplay(display)
    for _ in range(100):
        if not visible(): break
        time.sleep(.05)
    else: raise RuntimeError('close did not hide window')
    assert worker.poll() is None
    Path('/transport/hidden').touch()
    for _ in range(400):
        windows=visible()
        if windows: break
        assert worker.poll() is None
        time.sleep(.05)
    else: raise RuntimeError('repeat launch did not restore window')
    assert subprocess.check_output([tools+'/bin/xdotool','getwindowpid',windows[-1]],text=True).strip() == pid
    Path('/transport/restored').touch()
    assert worker.wait(timeout=25) == 0
    assert not visible()
finally:
    if worker is not None and worker.poll() is None:
        worker.terminate(); worker.wait(timeout=5)
    server.terminate(); server.wait(timeout=5)
'''

# Exercise media()'s real profile lock and repeat-launch path; replace only the
# Xpra display forwarding with a private X server so no outer WM is involved.
def private_session(run, app, files):
    for name in ['input', 'output', 'transport']:
        (run / name).mkdir()
    m.media_paths()[0].mkdir(parents=True, exist_ok=True)
    (run / 'passwd').write_text(f'legacy:x:{os.getuid()}:{os.getgid()}:Legacy:/home/legacy:/bin/sh\n')
    (run / 'group').write_text(f'legacy:x:{os.getgid()}:legacy\n')
    (run / 'machine-id').write_text('a'*32+'\n')
    (run / 'transport/inside.py').write_text(inside)
    (run / 'transport/tools').write_text(os.environ['TEST_TOOLS'])
    with wave.open(str(run / 'transport/silence.wav'), 'wb') as audio:
        audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0' * (8000 * 2 * 120))
    command = m.base_namespace(run, app=app)
    # Test executables only; still no outer display, bus, home or sound socket.
    position = command.index('--clearenv')
    command[position:position] = ['--ro-bind', '/nix/store', '/nix/store']
    subprocess.run(command + [m.CONFIG['python'], '/transport/inside.py'], check=True)

m.run_session = private_session
runtime = Path(os.environ['XDG_RUNTIME_DIR'])
(runtime/'pulse').mkdir()
pulse = subprocess.Popen([os.environ['TEST_TOOLS']+'/bin/pulseaudio', '-n', '--daemonize=no',
    '--use-pid-file=no', '--exit-idle-time=-1', '--disable-shm',
    '--load=module-null-sink sink_name=test',
    '--load=module-native-protocol-unix socket='+str(runtime/'pulse/native')+' auth-anonymous=1'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(100):
    if (runtime/'pulse/native').is_socket(): break
    assert pulse.poll() is None, 'private null audio server failed'
    time.sleep(.05)
else: raise AssertionError('private null audio server not ready')
process = multiprocessing.get_context('fork').Process(target=m.media, args=('rhythmbox',))
process.start()
base = Path.home()/'.local/state/unity-quantal/isolated'
def wait_file(name):
    for _ in range(400):
        candidates = list(base.glob('rhythmbox-*/transport/'+name))
        if candidates: return candidates[0].parent
        assert process.is_alive(), process.exitcode
        time.sleep(.05)
    raise AssertionError('missing lifecycle marker: '+name)
try:
    transport = wait_file('ready')
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(2)
        connection.connect(str(transport/'control.sock'))
        connection.sendall(b'run arbitrary command')
        assert connection.recv(32) == b'invalid'
    (transport/'hide').touch()
    wait_file('hidden')
    m.media('rhythmbox')
    wait_file('restored')
    m.media('rhythmbox', quit=True)
    process.join(10)
    assert not process.is_alive() and process.exitcode == 0
    assert not transport.exists(), 'private session was not cleaned up'
    m.media('rhythmbox', quit=True)  # No player should start for an idle Quit.
    assert not list(base.glob('rhythmbox-*/transport'))
    print('PASS: close hides, repeat launch restores same process, Quit exits and cleans up; commands restricted', flush=True)
finally:
    if process.is_alive():
        process.terminate(); process.join(5)
    pulse.terminate(); pulse.wait(timeout=5)
