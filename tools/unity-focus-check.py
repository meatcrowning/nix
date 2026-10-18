"""Run only inside unity-quantal-test.sh's isolated session."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

package = Path(sys.argv[1])
config = json.loads((package / 'libexec/unity-quantal/config.json').read_text())
runtime = str(package / 'bin/unity-quantal-runtime')
state = Path.home() / '.config/unity-quantal/display.json'


def setting(*args):
    return subprocess.check_output([runtime, '/usr/bin/gsettings', *args], text=True).strip()


def wait_for(fn):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(.2)
    raise AssertionError('Timed out waiting for focus theme')


def toggle(enabled):
    data = json.loads(state.read_text()) if state.exists() else {}
    data['dynamicFocus'] = enabled
    state.parent.mkdir(parents=True, exist_ok=True)
    temporary = state.with_suffix('.tmp')
    temporary.write_text(json.dumps(data))
    temporary.replace(state)


subprocess.run([config['focusPython'], '-c', '''
from PIL import Image
from pathlib import Path
for name, color in [('blue', '#3366cc'), ('green', '#22aa66'), ('gray', '#888888')]:
    Image.new('RGB', (48, 48), color).save(str(Path.home() / (name + '.png')))
'''], check=True)
setting('set', 'org.gnome.desktop.interface', 'gtk-theme', 'Ambiance-Dark')
setting('set', 'org.gnome.desktop.background', 'picture-uri', (Path.home() / 'blue.png').as_uri())
toggle(True)
first = wait_for(lambda: (lambda name: name if 'Unity-Focus-Ambiance-Dark-' in name else None)(
    setting('get', 'org.gnome.desktop.interface', 'gtk-theme')))
probe = '''from gi.repository import Gtk
w=Gtk.Button()
print(w.get_style_context().lookup_color('selected_bg_color'))
'''
color = subprocess.check_output([runtime, '/usr/bin/python2.7', '-c', probe], text=True)
assert 'True' in color and 'blue=0.780392' in color, color
print('PASS: wallpaper focus theme reaches original GTK: ' + color.strip())
native_css = Path.home() / '.themes' / first.strip("'") / 'gtk-3.20/gtk-main.css'
assert '#3263c7' in native_css.read_text(), native_css
print('PASS: native GTK theme carries the same wallpaper accent')
setting('set', 'org.gnome.desktop.background', 'picture-uri', (Path.home() / 'green.png').as_uri())
second = wait_for(lambda: (lambda name: name if 'Unity-Focus-' in name and name != first else None)(
    setting('get', 'org.gnome.desktop.interface', 'gtk-theme')))
assert first != second
setting('set', 'org.gnome.desktop.interface', 'gtk-theme', 'Radiance')
wait_for(lambda: 'Unity-Focus-Radiance-' in setting('get', 'org.gnome.desktop.interface', 'gtk-theme'))
toggle(False)
wait_for(lambda: setting('get', 'org.gnome.desktop.interface', 'gtk-theme') == "'Radiance'")
print('PASS: wallpaper updates, theme switching and toggle-off restoration')

# Missing pictures restore the base rather than leaving stale wallpaper colors.
toggle(True)
setting('set', 'org.gnome.desktop.background', 'picture-uri', 'file:///missing.png')
wait_for(lambda: setting('get', 'org.gnome.desktop.interface', 'gtk-theme') == "'Radiance'")
toggle(False)

spec = importlib.util.spec_from_file_location('actions', package / 'libexec/unity-quantal/file-actions.py')
actions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(actions)
entries = Path.home() / '.local/share/unity-quantal-session/file-manager/actions'
assert 'MimeTypes=image/*;' in (entries / 'unity-wallpaper.desktop').read_text()
assert 'Send to Galaxy Phone' in (entries / 'unity-phone.desktop').read_text()
for key in ('phone', 'wallpaper'):
    exported = subprocess.check_output([runtime, '/usr/bin/nautilus-actions-print', '--id=unity-' + key], text=True)
    assert 'file-actions.py ' + key + ' %F' in exported, exported
print('PASS: Nautilus-Actions loads both context menu entries')
calls = []
def fake_run(argv, **kwargs):
    calls.append(argv)
    return subprocess.CompletedProcess(argv, 0, 'test-id Galaxy test phone\n')
image = Path.home() / 'blue.png'
actions.perform('phone', [str(image)], config, fake_run)
assert calls[-1][-4:] == ['--device', 'test-id', '--share', str(image)]
setting('set', 'org.gnome.desktop.background', 'picture-options', 'none')
subprocess.run([runtime, '/usr/bin/nautilus-actions-run', '--id=unity-wallpaper',
                '--target=' + image.as_uri()], check=True)
wait_for(lambda: setting('get', 'org.gnome.desktop.background', 'picture-options') == "'zoom'")
wait_for(lambda: setting('get', 'org.gnome.desktop.background', 'picture-uri') == repr(image.as_uri()))
# Preserve an explicitly selected fit mode when wallpaper was already enabled.
setting('set', 'org.gnome.desktop.background', 'picture-options', 'scaled')
actions.perform('wallpaper', [str(image)], config)
assert setting('get', 'org.gnome.desktop.background', 'picture-options') == "'scaled'"
assert setting('get', 'org.gnome.desktop.background', 'picture-uri') == repr(image.as_uri())
print('PASS: Files actions installed, phone argv verified without sending, wallpaper updates')
ui_probe = '''
import ctypes, sys
from gi.repository import Gtk
sys.path.insert(0, %r)
import display
builder = Gtk.Builder()
builder.add_from_file('/usr/share/gnome-control-center/ui/background/background.ui')
# GI resolves symbols on its library handle; the native panel uses ELF lookup.
get_object = ctypes.CDLL(None).gtk_builder_get_object
get_object.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
get_object.restype = ctypes.c_void_p
assert get_object(hash(builder), 'background-panel')
box = builder.get_object('background-panel')
buttons = [w for w in box.get_children() if w.get_name() == 'unity-dynamic-focus-color']
assert len(buttons) == 1
button = buttons[0]
assert not button.get_active()
button.set_active(True)
assert display.load()['dynamicFocus'] is True
button.set_active(False)
assert display.load()['dynamicFocus'] is False
assert get_object(hash(builder), 'background-panel')
assert len([w for w in box.get_children() if w.get_name() == 'unity-dynamic-focus-color']) == 1
app = display.Settings()
app.register(None)
app.do_activate()
assert not hasattr(app, 'dynamic_focus')
print('PASS: native Appearance toggle persists both states; Display Settings has no duplicate')
''' % str(package / 'libexec/unity-quantal')
subprocess.run([runtime, '/usr/bin/env', 'LD_PRELOAD=' + config['appearanceFocus'],
                'UNITY_FOCUS_SETTINGS=' + str(package / 'libexec/unity-quantal/display.py'),
                '/usr/bin/python2.7', '-c', ui_probe], check=True)
