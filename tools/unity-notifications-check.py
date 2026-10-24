"""Only run inside unity-quantal-test.sh's private display, bus and home."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import time
import sys

package = Path(os.environ['UNITY_PACKAGE'])
config = json.loads((package / 'libexec/unity-quantal/config.json').read_text())
os.environ['GI_TYPELIB_PATH'] = config['typelibs']
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
context = GLib.MainContext.default()
name, path = 'org.freedesktop.Notifications', '/org/freedesktop/Notifications'
signals = []
bus.signal_subscribe(name, name, None, path, None, Gio.DBusSignalFlags.NONE,
                     lambda c, s, p, i, n, args: signals.append((n, args.unpack())))


def wait(predicate, message, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        result = predicate()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError(message)


def call(method, args):
    return bus.call_sync(name, path, name, method, args, None,
                         Gio.DBusCallFlags.NONE, 5000, None).unpack()


def notify(summary, extra=None):
    hints = {'transient': GLib.Variant('b', True), 'suppress-sound': GLib.Variant('b', True)}
    hints.update(extra or {})
    return call('Notify', GLib.Variant('(susssasa{sv}i)',
        ('Probe', 0, '', summary, 'Isolated test', ['default', 'Open'], hints, -1)))[0]


def xdo(*args):
    return subprocess.run(['xdotool', *map(str, args)], text=True, capture_output=True, check=False).stdout.strip()


def windows():
    return xdo('search', '--onlyvisible', '--name', '^notify-osd$').split()


def geometry(window):
    return {k: int(v) for k, v in (line.split('=') for line in xdo('getwindowgeometry', '--shell', window).splitlines())}


def click(window, corner=False):
    g = geometry(window)
    xdo('mousemove', g['X'] + (g['WIDTH'] - 24 if corner else g['WIDTH'] // 2),
        g['Y'] + (24 if corner else g['HEIGHT'] // 2))
    time.sleep(.1)
    xdo('click', 1)


# Wait for previous indicator-history probes to expire before measuring placement.
xdo('mousemove', 1, 600)
wait(lambda: not windows(), 'previous bubbles did not expire', timeout=35)
first = notify('Open probe')
window = wait(lambda: windows(), 'no notification window')[0]
g = geometry(window)
assert g['Y'] < 65, ('reserved volume gap remains', g)
click(window)
wait(lambda: ('ActionInvoked', (first, 'default')) in signals, 'body click did not invoke default')
wait(lambda: ('NotificationClosed', (first, 2)) in signals, 'body click did not close')
wait(lambda: not windows(), 'activated bubble remains visible')

second = notify('Dismiss probe')
window = wait(lambda: windows(), 'no dismiss bubble')[0]
click(window, corner=True)
wait(lambda: ('NotificationClosed', (second, 2)) in signals, 'corner click did not dismiss')
assert ('ActionInvoked', (second, 'default')) not in signals
wait(lambda: not windows(), 'dismissed bubble remains visible')

third = notify('Programmatic close')
wait(lambda: windows(), 'no close bubble')
call('CloseNotification', GLib.Variant('(u)', (third,)))
wait(lambda: ('NotificationClosed', (third, 3)) in signals, 'wrong programmatic close signal')
wait(lambda: not windows(), 'CloseNotification did not hide bubble')

# Exercise the actual GTK settings control, not a second writer of its file.
settings_script = package / 'libexec/unity-quantal/notification-settings.py'
script = Path.home() / 'notification-toggle.py'
script.write_text('''import imp, sys
from gi.repository import GLib, Gtk
module = imp.load_source('settings', sys.argv[1])
def toggle():
    window = Gtk.Window.list_toplevels()[0]
    button = window.get_child().get_children()[0]
    assert button.get_active() == (sys.argv[2] == 'off')
    button.set_active(not button.get_active())
    window.destroy()
    return False
GLib.idle_add(toggle)
module.main()
''')

def toggle(value):
    subprocess.run([str(package / 'bin/unity-quantal-runtime'), '/usr/bin/python2.7',
                    str(script), str(settings_script), value], check=True)

fourth = notify('Click through')
window = wait(lambda: windows(), 'no click-through bubble')[0]
toggle('on')
# Query the X input region directly; no interaction with the host seat.
x11 = ctypes.CDLL(config['libX11'])
xext_path = next(Path(p) / 'libXext.so.6' for p in config['modernLibraries'].split(':') if (Path(p) / 'libXext.so.6').exists())
xext = ctypes.CDLL(str(xext_path))
x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
x11.XOpenDisplay.restype = ctypes.c_void_p
display = x11.XOpenDisplay(None)
assert display
class Rect(ctypes.Structure):
    _fields_ = [('x', ctypes.c_short), ('y', ctypes.c_short), ('width', ctypes.c_ushort), ('height', ctypes.c_ushort)]
xext.XShapeGetRectangles.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
xext.XShapeGetRectangles.restype = ctypes.POINTER(Rect)
x11.XFree.argtypes = [ctypes.c_void_p]
x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
def input_area():
    count, order = ctypes.c_int(), ctypes.c_int()
    rects = xext.XShapeGetRectangles(display, int(window), 2, ctypes.byref(count), ctypes.byref(order))
    area = sum(rects[i].width * rects[i].height for i in range(count.value))
    x11.XFree(rects)
    return area
try:
    wait(lambda: input_area() <= 1, 'click-through setting did not reach the existing toast')
    toggle('off')
    wait(lambda: input_area() > 1, 'disabling click-through did not restore the input region')
finally:
    x11.XCloseDisplay(display)
click(window, corner=True)
wait(lambda: ('NotificationClosed', (fourth, 2)) in signals, 'live toggle broke dismissal')

# Ordinary and volume bubbles share the available slots without overlap.
xdo('mousemove', 1, 600)
wait(lambda: not windows(), 'previous bubble remains')
fifth = notify('Ordinary')
window = wait(lambda: windows(), 'no ordinary bubble')[0]
ordinary = geometry(window)
sixth = notify('Volume', {'x-canonical-private-synchronous': GLib.Variant('s', 'volume'), 'value': GLib.Variant('i', 50)})
wait(lambda: len(windows()) == 2, 'volume and ordinary bubbles do not coexist')
positions = sorted((geometry(w)['Y'], geometry(w)['HEIGHT']) for w in windows())
assert positions[1][0] > positions[0][0] + positions[0][1] - 30, positions
call('CloseNotification', GLib.Variant('(u)', (sixth,)))
call('CloseNotification', GLib.Variant('(u)', (fifth,)))
print('PASS: top placement, default action, corner dismissal, programmatic close, live GTK click-through toggle and volume coexistence', flush=True)
