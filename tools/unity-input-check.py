#!/usr/bin/env python3
"""Run only inside unity-quantal-test.sh's private desktop."""
import json
import ctypes
import os
from pathlib import Path
import re
import subprocess
import sys

assert os.environ['HOME'] == '/home/unity-test'
assert os.environ['DISPLAY'] == ':93'
assert Path('/work/inside.sh').is_file()
package = Path(os.environ['UNITY_PACKAGE'])
config = json.loads((package / 'libexec/unity-quantal/config.json').read_text())
launcher = (package / 'bin/unity-quantal-terminal').read_text()
wrapper = Path(re.search(r'exec (\S+)/bin/unity-terminal', launcher)[1]) / 'bin/unity-terminal'
os.environ['GI_TYPELIB_PATH'] = next(p.decode() for p in wrapper.read_bytes().split(b'\0')
    if p.startswith(b'/nix/store/') and b'/lib/girepository-1.0:' in p)
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Gio, GLib
assert Gtk.get_minor_version() > 6
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
name = 'org.freedesktop.Notifications'
def notify(method, parameters):
    return bus.call_sync(name, '/org/freedesktop/Notifications', name, method,
                         parameters, None, Gio.DBusCallFlags.NONE, 10000, None)
capabilities = notify('GetCapabilities', None).unpack()[0]
assert 'actions' in capabilities and 'body' in capabilities, capabilities
result = notify('Notify', GLib.Variant('(susssasa{sv}i)', ('Vivaldi', 0, 'dialog-information',
    'Browser notification', 'Native bubble from isolated test', ['default', 'Activate'],
    {'urgency': GLib.Variant('y', 1)}, 25000)))
assert result.unpack()[0] > 0
print('PASS: native notification adapter accepts Chromium capabilities, actions and typed hints', flush=True)
private_bus = next(Path(os.environ['XDG_RUNTIME_DIR']).glob('unity-notifications-*/bus'))
native = Gio.DBusConnection.new_for_address_sync('unix:path='+str(private_bus),
    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
def locked(connection):
    return connection.call_sync('org.gnome.ScreenSaver', '/org/gnome/ScreenSaver', 'org.gnome.ScreenSaver',
                                'GetActive', None, None, Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
assert locked(native) == locked(bus)
print('PASS: native bubbles retain the session lock-state query', flush=True)

def check_passive_grabs(window):
    library = next(Path(p)/'libX11.so.6' for p in config['modernLibraries'].split(':')
                   if (Path(p)/'libX11.so.6').exists())
    x = ctypes.CDLL(str(library))
    ptr, ulong, uint = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_uint
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]; x.XOpenDisplay.restype = ptr
    x.XQueryTree.argtypes = [ptr, ulong, ctypes.POINTER(ulong), ctypes.POINTER(ulong),
                            ctypes.POINTER(ptr), ctypes.POINTER(uint)]
    x.XGrabButton.argtypes = [ptr, uint, uint, ulong, ctypes.c_int, uint,
                             ctypes.c_int, ctypes.c_int, ulong, ulong]
    x.XUngrabButton.argtypes = [ptr, uint, uint, ulong]
    x.XSync.argtypes = [ptr, ctypes.c_int]
    x.XCloseDisplay.argtypes = [ptr]
    x.XFree.argtypes = [ptr]
    x.XSetErrorHandler.argtypes = [ptr]; x.XSetErrorHandler.restype = ptr
    errors = []
    @ctypes.CFUNCTYPE(ctypes.c_int, ptr, ptr)
    def error(display, event):
        errors.append(True)
        return 0
    display = x.XOpenDisplay(b':93')
    assert display
    previous = x.XSetErrorHandler(error)
    click_grabbed = False
    try:
        while True:
            root, parent, children, count = ulong(), ulong(), ptr(), uint()
            assert x.XQueryTree(display, window, ctypes.byref(root), ctypes.byref(parent),
                                ctypes.byref(children), ctypes.byref(count))
            if children:
                x.XFree(children)
            if parent.value == root.value:
                break
            window = parent.value
            for button in (1, 5):
                errors.clear()
                x.XGrabButton(display, button, 0, window, 0, 4, 1, 1, 0, 0)
                x.XSync(display, 0)
                blocked = bool(errors)
                if not blocked:
                    x.XUngrabButton(display, button, 0, window)
                if button == 5:
                    assert not blocked, 'Compiz still passively grabs bare wheel events'
                else:
                    click_grabbed |= blocked
        assert click_grabbed, 'did not find Compiz click-to-focus grab'
    finally:
        x.XSetErrorHandler(previous)
        x.XCloseDisplay(display)
    print('PASS: Compiz retains click grabs and releases unmodified wheel grabs', flush=True)

view = Gtk.Window(title='unfocused-scroll-probe')
view.set_default_size(360, 240)
scroll = Gtk.ScrolledWindow()
text = Gtk.TextView()
text.get_buffer().set_text('\n'.join('Scrollable line %d' % i for i in range(200)))
scroll.add(text)
view.add(scroll)
view.show_all()
sink = Gtk.Window(title='scroll-focus-sink')
sink.add(Gtk.Entry())
sink.set_default_size(240, 120)
sink.show_all()
failed = []
stage = [0]
def command(*args):
    return subprocess.check_output(['xdotool', *map(str, args)], text=True).strip()
def check():
    try:
        if stage[0] == 0:
            source = command('search', '--name', '^unfocused-scroll-probe$')
            target = command('search', '--name', '^scroll-focus-sink$')
            command('windowmove', source, 150, 150)
            command('windowmove', target, 800, 500)
            command('windowactivate', target)
            command('mousemove', '--window', source, 100, 100)
            stage.append(target)
        elif stage[0] == 1:
            check_passive_grabs(int(command('search', '--name', '^unfocused-scroll-probe$')))
            command('click', '--repeat', 5, '--delay', 40, 5)
        elif stage[0] == 2:
            assert scroll.get_vadjustment().get_value() > 0, 'wheel did not reach unfocused GTK window'
            assert command('getactivewindow') == stage[1], 'scroll stole focus'
            # Left click must still activate the window after narrowing grabs.
            command('click', 1)
        elif stage[0] == 3:
            assert command('getactivewindow') != stage[1], 'click-to-focus broke'
            print('PASS: unfocused GTK wheel scrolling preserves focus; click-to-focus still works', flush=True)
            Gtk.main_quit()
            return False
        stage[0] += 1
        return True
    except Exception as error:
        failed.append(error)
        Gtk.main_quit()
        return False
GLib.timeout_add(500, check)
Gtk.main()
view.destroy()
sink.destroy()
if failed:
    raise failed[0]

# Exercise the real browser with an empty, disposable profile and a local
# extension. The enclosing namespace has no host network, home, bus or display.
if os.environ.get('UNITY_TEST_VIVALDI'):
    import signal
    import time
    extension = Path('/work/notification-extension')
    extension.mkdir()
    (extension/'manifest.json').write_text(json.dumps(dict(manifest_version=3,
        name='Isolated notification test', version='1.0', permissions=['notifications'],
        background=dict(service_worker='background.js'))))
    subprocess.run(['magick', '-size', '32x32', 'xc:blue', str(extension/'icon.png')], check=True)
    (extension/'background.js').write_text("chrome.runtime.onInstalled.addListener(() => "
        "chrome.notifications.create('test', {type:'basic', iconUrl:'icon.png', "
        "title:'Isolated Vivaldi native test', message:'Native bubble protocol check'}, "
        "id => console.error('notification test:', id, chrome.runtime.lastError))); ")
    log_path = Path('/work/notification-monitor.log')
    with log_path.open('w') as log, Path('/work/vivaldi.log').open('w') as browser_log:
        monitor = subprocess.Popen(['dbus-monitor', '--session',
            "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"],
            stdout=log, stderr=subprocess.STDOUT)
        browser = None
        try:
            time.sleep(.3)
            browser = subprocess.Popen([os.environ['UNITY_TEST_VIVALDI'],
                '--no-sandbox', '--no-first-run', '--no-default-browser-check',
                '--disable-background-networking', '--disable-gpu', '--password-store=basic',
                '--enable-logging=stderr',
                '--user-data-dir=/work/vivaldi-profile', '--load-extension='+str(extension),
                'about:blank'], stdout=browser_log, stderr=subprocess.STDOUT, start_new_session=True)
            for _ in range(300):
                if 'Isolated Vivaldi native test' in log_path.read_text():
                    print('PASS: Vivaldi delivers a real browser notification to the native service', flush=True)
                    break
                if browser.poll() is not None:
                    raise AssertionError('Isolated browser exited: '+Path('/work/vivaldi.log').read_text()[-2000:])
                time.sleep(.1)
            else:
                raise AssertionError('Vivaldi did not send the native notification; see /work/vivaldi.log')
        finally:
            if browser is not None and browser.poll() is None:
                os.killpg(browser.pid, signal.SIGTERM)
                try:
                    browser.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(browser.pid, signal.SIGKILL)
                    browser.wait()
            monitor.terminate()
            monitor.wait(timeout=5)
