#!/usr/bin/env bash
# Both the outer desktop and every hostile probe are disposable namespaces.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
export QT_QPA_PLATFORM=offscreen
source "$repo/tools/lib/session-guard.sh"
sg_require_offscreen
package=${1:?session package required}
test_tools=${2:?test tools required}
python=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["python"])' "$package/libexec/unity-quantal/config.json")
run=$(mktemp -d /tmp/unity-isolated-test.XXXXXX)
mkdir -p "$run/home"
printf 'private host data\n' > "$run/home/private.txt"
cat > "$run/check.py" <<'PY'
import ctypes
import importlib.util
import json
import multiprocessing
import os
import re
from pathlib import Path
import subprocess
import sys
import time

spec = importlib.util.spec_from_file_location('isolated', sys.argv[1] + '/libexec/unity-quantal/isolated.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

probe = Path('/work/probe')
probe.mkdir()
for name in ['input','output','transport']:
    (probe/name).mkdir()
(probe/'passwd').write_text(f'legacy:x:{os.getuid()}:{os.getgid()}:Legacy:/home/legacy:/bin/sh\n')
(probe/'group').write_text(f'legacy:x:{os.getgid()}:legacy\n')
(probe/'machine-id').write_text('a'*32+'\n')
script = '''
import ctypes, os, pathlib, socket
assert not pathlib.Path('/home/test/private.txt').exists()
assert not pathlib.Path('/run/user/1000/bus').exists()
assert not pathlib.Path('/tmp/.X11-unix/X93').exists()
assert not pathlib.Path('/dev/dri').exists()
assert not pathlib.Path('/dev/input').exists()
assert not pathlib.Path('/sys').exists()
assert 'UNITY_QUANTAL_HOST_SOCKET' not in os.environ
assert 'DBUS_SESSION_BUS_ADDRESS' not in os.environ
assert 'DISPLAY' not in os.environ
assert len([p for p in pathlib.Path('/proc').iterdir() if p.name.isdigit()]) < 5
try: socket.socket(socket.AF_INET, socket.SOCK_STREAM)
except PermissionError: pass
else: raise AssertionError('network socket permitted')
assert ctypes.CDLL(None).unshare(0x10000000) == -1
s=socket.socket(socket.AF_UNIX)
try: s.connect('\\0/tmp/.X11-unix/X93')
except OSError: pass
else: raise AssertionError('outer abstract X socket reachable')
print('PASS: filesystem, processes, devices, network, X11 and bus isolation')
'''
subprocess.run(m.base_namespace(probe)+[m.CONFIG['python'],'-c',script],check=True)
# Export must never follow malicious links, FIFOs, or copy executable modes.
(probe/'output/link').symlink_to('/home/test/private.txt')
try: m.regular_files(probe/'output')
except ValueError: pass
else: raise AssertionError('symlink export accepted')
(probe/'output/link').unlink()
os.mkfifo(probe/'output/pipe')
try: m.regular_files(probe/'output')
except ValueError: pass
else: raise AssertionError('FIFO export accepted')
(probe/'output/pipe').unlink()
(probe/'output/text').write_text('edited text')
(probe/'output/text').chmod(0o755)
m.copy_regular(probe/'output/text',probe/'exported')
assert (probe/'exported').read_text()=='edited text'
assert (probe/'exported').stat().st_mode & 0o777 == 0o600
print('PASS: export rejects links/special files and strips executable permissions',flush=True)
help_text=subprocess.check_output(m.base_namespace(probe)+[m.CONFIG['python'],'/runner/isolated.py','worker','file-roller','--help'],text=True)
assert '--extract-to' in help_text and '--force' in help_text


# Defaults resolve to these entries only under Unity; generic choices survive.
config = Path.home()/'.config'
data = Path.home()/'.local/share'
config.mkdir(parents=True, exist_ok=True)
(data/'applications').mkdir(parents=True, exist_ok=True)
(data/'applications/native-editor.desktop').write_text('[Desktop Entry]\nType=Application\nName=Native editor\nExec=/bin/true %F\nMimeType=text/plain;\n')
(config/'mimeapps.list').write_text('[Default Applications]\ntext/plain=native-editor.desktop;\n')
m.install_defaults({'config_home':str(config),'data_home':str(data)})
for desktop, expected in [('Unity','unity-original-gedit.desktop'),('KDE','native-editor.desktop')]:
    env=os.environ.copy()
    env.update(XDG_CURRENT_DESKTOP=desktop,XDG_DATA_DIRS=sys.argv[1]+'/share')
    result=subprocess.check_output(['gio','mime','text/plain'],text=True,env=env)
    assert expected in result.splitlines()[0],result
print('PASS: Unity defaults and preserved KDE defaults',flush=True)

def close_window(window):
    assert os.environ['DISPLAY']==':93' and Path('/work/inside.sh').is_file()
    library=next(Path(p)/'libX11.so.6' for p in m.CONFIG['modernLibraries'].split(':') if (Path(p)/'libX11.so.6').exists())
    x=ctypes.CDLL(str(library))
    class Message(ctypes.Structure):
        _fields_=[('type',ctypes.c_int),('serial',ctypes.c_ulong),('send_event',ctypes.c_int),('display',ctypes.c_void_p),('window',ctypes.c_ulong),('message_type',ctypes.c_ulong),('format',ctypes.c_int),('data',ctypes.c_long*5)]
    class Event(ctypes.Union):
        _fields_=[('message',Message),('padding',ctypes.c_long*24)]
    x.XOpenDisplay.argtypes=[ctypes.c_char_p]; x.XOpenDisplay.restype=ctypes.c_void_p
    x.XInternAtom.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int]; x.XInternAtom.restype=ctypes.c_ulong
    x.XSendEvent.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_long,ctypes.POINTER(Event)]
    x.XCloseDisplay.argtypes=[ctypes.c_void_p]
    display=x.XOpenDisplay(b':93'); assert display
    event=Event()
    event.message=Message(33,0,1,display,window,x.XInternAtom(display,b'WM_PROTOCOLS',0),32,(ctypes.c_long*5)(x.XInternAtom(display,b'WM_DELETE_WINDOW',0),0,0,0,0))
    assert x.XSendEvent(display,window,0,0,ctypes.byref(event))
    x.XCloseDisplay(display)

for app in m.APPS:
    run=Path('/work')/app
    run.mkdir()
    (run/'input').mkdir()
    (run/'output').mkdir()
    files=[]
    if app == 'gedit':
        (run/'output/example.txt').write_text('Private document example')
        files=['/home/legacy/Documents/example.txt']
    elif app == 'eog':
        subprocess.run(['magick','-size','16x16','xc:red',str(run/'input/example.png')],check=True)
        files=['/home/legacy/Input/example.png']
    elif app == 'file-roller':
        import zipfile
        with zipfile.ZipFile(run/'input/example.zip','w') as archive:
            archive.writestr('example.txt','Private archive example')
        files=['/home/legacy/Input/example.zip']
    process=multiprocessing.get_context('fork').Process(target=m.run_session,args=(run,app,files))
    process.start()
    try:
        deadline=time.monotonic()+30
        found=False
        while time.monotonic()<deadline and process.is_alive():
            tree=subprocess.run(['xwininfo','-root','-tree'],capture_output=True,text=True).stdout
            if any(name in tree for name in {'gedit':['gedit','Gedit'], 'eog':['eog','Eog'], 'file-roller':['file-roller','File-roller'], 'gcalctool':['gcalctool','Gcalctool']}[app]):
                found=True
                break
            time.sleep(.2)
        if not found:
            for log in ['server.log','client.log']:
                p=run/log
                if p.exists(): print(p.read_text()[-8000:])
            raise AssertionError('No isolated window for '+app)
        candidates=[line for line in tree.splitlines() if app.lower() in line.lower() and re.search(r' [1-9][0-9]{1,}x[1-9][0-9]{1,}[+-]',line)]
        assert candidates,tree
        close_window(int(re.search(r'0x[0-9a-f]+',candidates[0]).group(),16))
        process.join(20)
        assert not process.is_alive() and process.exitcode==0
        print('PASS: private display and sandboxed client for '+app,flush=True)
        if app == 'file-roller':
            import shutil
            extract=Path('/work/extract')
            (extract/'input').mkdir(parents=True)
            shutil.copyfile(run/'input/example.zip',extract/'input/example.zip')
            m.run_session(extract,app,['--extract-to=/home/legacy/Documents','--force',*files])
            assert (extract/'output/example.txt').read_text()=='Private archive example'
            print('PASS: original Archive Manager extracts with maintained helpers',flush=True)
    finally:
        if process.is_alive():
            process.terminate(); process.join(5)
PY
cat > "$run/inside.sh" <<'SH'
set -euo pipefail
source /guard.sh
sg_require_offscreen
mkdir -p /run/user/1000 /tmp/.X11-unix
chmod 700 /run/user/1000
trap 'kill $(jobs -pr) 2>/dev/null || true; wait || true' EXIT
Xvfb :93 -screen 0 1600x1200x24 -nolisten tcp -ac >/work/xserver.log 2>&1 &
export DISPLAY=:93
for _ in {1..100}; do
  test -S /tmp/.X11-unix/X93 && break
  sleep .05
done
"$TEST_PYTHON" /work/check.py "$UNITY_PACKAGE"
SH
echo "Isolated application logs: $run"
"$test_tools/bin/timeout" --kill-after=5s 180s "$test_tools/bin/bwrap" \
  --die-with-parent --new-session --unshare-all --ro-bind /nix /nix \
  --proc /proc --dev /dev --symlink "$test_tools/bin" /bin --tmpfs /tmp --tmpfs /run \
  --bind "$run" /work --bind "$run/home" /home/test \
  --ro-bind "$repo/tools/lib/session-guard.sh" /guard.sh \
  --clearenv --setenv HOME /home/test --setenv USER test --setenv LOGNAME test \
  --setenv PATH "$test_tools/bin" --setenv QT_QPA_PLATFORM offscreen \
  --setenv XDG_RUNTIME_DIR /run/user/1000 --setenv XDG_CURRENT_DESKTOP Unity \
  --setenv UNITY_PACKAGE "$package" --setenv TEST_PYTHON "$python" \
  --chdir /work "$test_tools/bin/bash" /work/inside.sh
