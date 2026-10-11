"""Real event producers and PCM capture inside unity-quantal-test.sh only."""
import array
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

assert os.environ['HOME'] == '/home/unity-test'
assert os.environ['DISPLAY'] == ':93'
assert os.environ['PULSE_SERVER'] == 'unix:/run/user/1000/pulse/native'
assert not Path('/dev/snd').exists()
package = Path(os.environ['UNITY_PACKAGE'])
tools = Path(os.environ['UNITY_TEST_TOOLS'])
config = json.loads((package / 'libexec/unity-quantal/config.json').read_text())
runtime = package / 'bin/unity-quantal-runtime'
log = Path.home() / '.local/state/unity-quantal/session.log'


def run(*args, **kw):
    return subprocess.run(list(map(str, args)), check=True, timeout=20, **kw)


def wait_for(predicate, label):
    for _ in range(120):
        if predicate():
            return
        time.sleep(.1)
    raise AssertionError(label)


def capture(label, producer, audible=True):
    target = Path('/work') / (label + '.pcm')
    with target.open('wb') as stream:
        recorder = subprocess.Popen([str(tools / 'bin/parec'), '--raw', '--format=s16le', '--rate=44100',
            '--channels=2', '--latency-msec=10', '--device=unity-test.monitor'], stdout=stream)
        try:
            time.sleep(.15)
            producer()
            time.sleep(.35)
        finally:
            recorder.terminate()
            recorder.wait(timeout=3)
    data = array.array('h')
    data.frombytes(target.read_bytes())
    peak = max(map(abs, data), default=0)
    assert (peak > 10) == audible, (label, len(data), peak, audible)
    print('PASS: %s, captured %d samples, peak %d' % (label, len(data), peak), flush=True)


def get(key):
    return run(runtime, '/usr/bin/gsettings', 'get', 'org.gnome.desktop.sound', key,
               capture_output=True, text=True).stdout.strip()


def set_sound(key, value):
    run(runtime, '/usr/bin/gsettings', 'set', 'org.gnome.desktop.sound', key, value)
    time.sleep(.3)


wait_for(lambda: 'sound desktop-login: complete' in log.read_text(), 'login sound completion')
assert log.read_text().count('sound desktop-login: complete') == 1
assert get('theme-name') == "'ubuntu'" and get('event-sounds') == 'true'
assert get('input-feedback-sounds') == 'true'
run(runtime, '/usr/bin/python2.7', '-c', 'import ctypes; ctypes.CDLL("/usr/lib/x86_64-linux-gnu/gtk-3.0/modules/libcanberra-gtk3-module.so")')
run(runtime, '/usr/bin/python2.7', '-c',
    'from gi.repository import Gtk; s=Gtk.Settings.get_default(); print([(k,s.get_property(k)) for k in ["gtk-enable-event-sounds","gtk-enable-input-feedback-sounds","gtk-sound-theme-name"]])')

# Resolve every original Ubuntu event by name through the repaired original
# libcanberra, not a direct-file player. Record actual decoded PCM for each.
events = sorted(p.stem for p in (Path(config['runtime']) / 'usr/share/sounds/ubuntu/stereo').glob('*.ogg'))
assert len(events) == 19, events
if os.environ.get('UNITY_TEST_SOUND_HOOKS_ONLY') != '1':
    for event in events + ['audio-volume-change', 'trash-empty']:
        capture(event, lambda event=event: run(runtime, '/usr/bin/canberra-gtk-play', '--id=' + event))

# The native lifecycle player must find the same original theme too.
capture('native-message', lambda: run(package / 'bin/unity-quantal-sounds', 'play', 'message'))
set_sound('event-sounds', 'false')
capture('disabled', lambda: run(package / 'bin/unity-quantal-sounds', 'play', 'message'), audible=False)
set_sound('event-sounds', 'true')

# Original GTK module emits sounds in response to real widget signals. Only
# the private X server receives synthesized events; the host seat is absent.
gtk = Path.home() / 'gtk-sound.py'
gtk.write_text('''from gi.repository import Gtk, GLib
w = Gtk.Window()
w.set_title("unity-sound-widget")
b = Gtk.ToggleButton(label="Sound probe")
w.add(b)
w.show_all()
b.grab_focus()
loop = GLib.MainLoop()
GLib.timeout_add(3000, lambda: (loop.quit(), False)[1])
loop.run()
assert b.get_active()
w.destroy()
''')
def gtk_probe():
    child = subprocess.Popen([str(runtime), '/usr/bin/python2.7', str(gtk)])
    try:
        time.sleep(.8)
        window = run(tools / 'bin/xdotool', 'search', '--name', '^unity-sound-widget$',
                     capture_output=True, text=True).stdout.strip().splitlines()[0]
        run(tools / 'bin/xdotool', 'windowactivate', '--sync', window)
        run(tools / 'bin/xdotool', 'key', 'space')
        assert child.wait(timeout=8) == 0
    finally:
        if child.poll() is None:
            child.terminate(); child.wait(timeout=3)
capture('gtk-toggle', gtk_probe)
key_target = subprocess.Popen([str(tools / 'bin/xmessage'), '-name', 'volume-key-probe', '-buttons', 'ok:0', 'Private key target'])
time.sleep(.6)
key_window = run(tools / 'bin/xdotool', 'search', '--name', '^volume-key-probe$', capture_output=True, text=True).stdout.strip()
run(tools / 'bin/xdotool', 'windowactivate', '--sync', key_window)
capture('media-key-feedback', lambda: (run(tools / 'bin/xdotool', 'key', 'XF86AudioLowerVolume'), time.sleep(1)))
volume = run(tools / 'bin/pactl', 'get-sink-volume', 'unity-test', capture_output=True, text=True).stdout
assert '95%' in volume, volume
capture('quiet-media-key', lambda: (run(tools / 'bin/xdotool', 'key', 'shift+XF86AudioLowerVolume'), time.sleep(1)), audible=False)
set_sound('event-sounds', 'false')
capture('disabled-media-key', lambda: (run(tools / 'bin/xdotool', 'key', 'XF86AudioLowerVolume'), time.sleep(1)), audible=False)
set_sound('event-sounds', 'true')
key_target.terminate(); key_target.wait(timeout=3)

# Refresh must preserve disabled preferences and never replay login.
set_sound('input-feedback-sounds', 'false')
run(package / 'bin/unity-quantal-refresh')
time.sleep(1)
assert get('input-feedback-sounds') == 'false'
assert log.read_text().count('sound desktop-login: complete') == 1
print('PASS: refresh preserves preferences and does not replay login', flush=True)

trash = Path.home() / '.local/share/Trash/files'
trash.mkdir(parents=True, exist_ok=True)
capture('trash-add-silent', lambda: ((trash / 'probe').touch(), time.sleep(1)), audible=False)
capture('trash-empty-hook', lambda: ((trash / 'probe').unlink(), time.sleep(1)))

# Notification sounds are explicit hints, including suppression and locking.
def notify(hints, event=None):
    run(tools / 'bin/gdbus', 'call', '--session', '--dest', 'org.freedesktop.Notifications',
        '--object-path', '/org/freedesktop/Notifications', '--method', 'org.freedesktop.Notifications.Notify',
        'unity-sound-test', '0', 'notification-message-im', 'Isolated sound', 'Probe', '[]', hints, '1500')
    if event:
        wait_for(lambda: 'sound ' + event + ': complete' in log.read_text(), 'notification sound completion')
    else:
        time.sleep(1)

capture('notification-hint', lambda: notify("{'sound-name': <'message-new-instant'>}", 'message-new-instant'))
capture('notification-suppressed', lambda: notify("{'sound-name': <'message'>, 'suppress-sound': <true>}"), audible=False)

# Use ALSA's file PCM for the greeter output in the same device-free namespace.
# The same aplay command decodes the build-time WAV; no mixer or hardware opens.
alsa = Path('/work/alsa.conf')
alsa.write_text('pcm.capture { type file slave.pcm { type null } file "/work/greeter.pcm" format "raw" }\n')
spec = importlib.util.spec_from_file_location('greeter', package / 'libexec/unity-quantal/greeter-sound.py')
greeter = importlib.util.module_from_spec(spec); spec.loader.exec_module(greeter)
proc = Path('/work/asound'); (proc / 'card2').mkdir(parents=True)
(proc / 'pcm').write_text('00-03: HDMI : HDMI : playback 1\n02-00: ALC897 Analog : ALC897 Analog : playback 1\n')
(proc / 'card2/id').write_text('Generic_1\n')
assert greeter.analog_device(proc) == 'plughw:CARD=Generic_1,DEV=0'
select_device = greeter.analog_device
greeter.analog_device = lambda: select_device(proc)
greeter.greeter_active = lambda: True
player = Path('/work/greeter-aplay')
player.write_text('#!' + config['bash'] + '\nfor arg in "$@"; do file="$arg"; done\n'
                  'ALSA_CONFIG_PATH=/work/alsa.conf exec ' + config['aplay'] + ' -q -D capture "$file"\n')
player.chmod(0o700)
greeter.CONFIG['aplay'] = str(player)
import sys
saved_argv = sys.argv; sys.argv = ['greeter-sound.py', '--worker']
greeter.main()
sys.argv = saved_argv
pcm = array.array('h'); pcm.frombytes(Path('/work/greeter.pcm').read_bytes())
assert max(map(abs, pcm)) > 10
greeter.greeter_active = lambda: False
before = Path('/work/greeter.pcm').stat().st_mtime_ns
sys.argv = ['greeter-sound.py', '--worker']; greeter.main(); sys.argv = saved_argv
assert Path('/work/greeter.pcm').stat().st_mtime_ns == before
print('PASS: actual greeter worker selects analog PCM, decodes through ALSA, and skips an active user', flush=True)

def logout():
    run(tools / 'bin/gdbus', 'call', '--session', '--dest', 'org.gnome.SessionManager',
        '--object-path', '/org/gnome/SessionManager', '--method', 'org.gnome.SessionManager.Logout', '1')
    wait_for(lambda: 'sound desktop-logout: complete' in log.read_text(), 'logout sound completion')
capture('logout-hook', logout)
print('PASS: all original assets, GTK events, native hooks, disable controls, refresh, notification hints and logout', flush=True)
