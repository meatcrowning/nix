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
    deadline = time.monotonic() + 60
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
subprocess.run([config['focusPython'], '-c', """
import importlib.util, sys, tempfile
from pathlib import Path
spec = importlib.util.spec_from_file_location('focus_theme', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
svg = '<svg><stop style="stop-color:#f90"/><path fill="url(#abc)" href="#abcdef" stroke="rgba(240,120,70,.5)"/></svg>'
result = m.stylesheet(svg, (50, 100, 200))
assert 'url(#abc)' in result and 'href="#abcdef"' in result
assert '#f90' not in result and 'rgba(240,120,70' not in result and ',.5)' in result
assert m.recolor((255, 0, 0), (50, 100, 200)) == (255, 0, 0)
assert m.recolor((239, 57, 57), (50, 100, 200), True)[2] > 190
assert m.recolor((255, 255, 255), (50, 100, 200), True) == (255, 255, 255)
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    for content in (b'', b'not a valid image', svg.encode()):
        (root / 'mislabelled.png').write_bytes(content)
        m.asset(root / 'mislabelled.png', root / 'output.png', (50, 100, 200))
        assert (root / 'output.png').read_bytes() == (result.encode() if content == svg.encode() else content)

""", str(package / 'libexec/unity-quantal/focus-theme.py')], check=True)
setting('set', 'org.gnome.desktop.interface', 'icon-theme', 'ubuntu-mono-dark')
setting('set', 'org.gnome.desktop.interface', 'gtk-theme', 'Ambiance-Dark')
setting('set', 'org.gnome.desktop.wm.preferences', 'theme', 'Ambiance')
setting('set', 'org.gnome.desktop.background', 'picture-uri', (Path.home() / 'blue.png').as_uri())
toggle(True)
first = wait_for(lambda: (lambda name: name if 'Unity-Focus-Ambiance-Dark-' in name else None)(
    setting('get', 'org.gnome.desktop.interface', 'gtk-theme')))
wait_for(lambda: setting('get', 'org.gnome.desktop.wm.preferences', 'theme') == first)
print('PASS: Ambiance decorations follow the Ambiance Dark wallpaper accent')
probe = '''from gi.repository import Gtk
w=Gtk.Button()
print(w.get_style_context().lookup_color('selected_bg_color'))
'''
color = subprocess.check_output([runtime, '/usr/bin/python2.7', '-c', probe], text=True)
assert 'True' in color and 'blue=0.780392' in color, color
print('PASS: wallpaper focus theme reaches original GTK: ' + color.strip())
# Brightness updates must rebuild both themes and icons, then restore the
# exact default cache entry without changing the wallpaper or enable state.
def set_brightness(value):
    subprocess.run([runtime, '/usr/bin/python2.7',
                    str(package / 'libexec/unity-quantal/display.py'),
                    'focus-brightness=' + str(value)], check=True)

original_icon = setting('get', 'org.gnome.desktop.interface', 'icon-theme')
set_brightness(50)
dimmed = wait_for(lambda: (lambda name: name if 'Unity-Focus-' in name and name != first else None)(
    setting('get', 'org.gnome.desktop.interface', 'gtk-theme')))
assert setting('get', 'org.gnome.desktop.interface', 'icon-theme') != original_icon
dark = (Path.home() / '.themes' / dimmed.strip("'") / '.complete').read_text()
normal = (Path.home() / '.themes' / first.strip("'") / '.complete').read_text()
assert all(int(dark[i:i+2], 16) <= int(normal[i:i+2], 16) for i in (1, 3, 5))
set_brightness(125)
brightened = wait_for(lambda: (lambda name: name if 'Unity-Focus-' in name and name not in (first, dimmed) else None)(
    setting('get', 'org.gnome.desktop.interface', 'gtk-theme')))
set_brightness(100)
wait_for(lambda: setting('get', 'org.gnome.desktop.interface', 'gtk-theme') == first)
assert setting('get', 'org.gnome.desktop.interface', 'icon-theme') == original_icon
print('PASS: brightness changes themes and icons and restores the default color')
native_css = Path.home() / '.themes' / first.strip("'") / 'gtk-3.20/gtk-main.css'
assert '#f07746' not in native_css.read_text(), native_css
print('PASS: native GTK theme carries the same wallpaper accent')
icon_name = setting('get', 'org.gnome.desktop.interface', 'icon-theme')
assert 'Unity-Focus-Icons-ubuntu-mono-dark-' in icon_name, icon_name
icon_probe = """from gi.repository import Gtk
icon = Gtk.IconTheme.get_default().lookup_icon('folder', 48, 0)
assert icon is not None
assert 'Unity-Focus-Icons-Humanity-' in icon.get_filename(), icon.get_filename()
picture = icon.load_icon()
pixels = bytearray(picture.get_pixels())
blue = orange = 0
for y in range(picture.get_height()):
 for x in range(picture.get_width()):
  offset = y * picture.get_rowstride() + x * picture.get_n_channels()
  r,g,b = pixels[offset:offset+3]
  if b > r * 1.3 and b > g: blue += 1
  if r > b * 1.5 and r > g * 1.1: orange += 1
assert blue > 100 and orange == 0, (blue, orange)
print('PASS: original GTK resolves inherited Humanity folder icons with wallpaper colors')
"""
subprocess.run([runtime, '/usr/bin/python2.7', '-c', icon_probe], check=True)
for filename in ('unity-original-nautilus.desktop', 'painter.desktop'):
    entry = Path(__import__('os').environ['UNITY_QUANTAL_SESSION_DIR']) / 'applications' / filename
    if entry.exists():
        assert not any(line.startswith('Icon=/') for line in entry.read_text().splitlines()), filename

setting('set', 'org.gnome.desktop.background', 'picture-uri', (Path.home() / 'green.png').as_uri())
second = wait_for(lambda: (lambda name: name if 'Unity-Focus-' in name and name != first else None)(
    setting('get', 'org.gnome.desktop.interface', 'gtk-theme')))
assert first != second
wait_for(lambda: setting('get', 'org.gnome.desktop.wm.preferences', 'theme') == second)
assert setting('get', 'org.gnome.desktop.interface', 'icon-theme') != icon_name
# Exercise both PNG loader boundaries in one original-GTK process, including
# theme changes and disabling. No shell UI or input is needed.
shell_probe = r"""
import ctypes, os, sys
from gi.repository import Gtk, GdkPixbuf
api = ctypes.CDLL(None)
api.fread.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p]
api.fread.restype = ctypes.c_size_t
api.fclose.argtypes = [ctypes.c_void_p]
settings = Gtk.Settings.get_default()
for theme in sys.argv[1:]:
 settings.set_property('gtk-theme-name', theme)
 for name in ['close_dash.png', 'close_dash_prelight.png', 'close_dash_pressed.png',
              'close_dash_disabled.png', 'switcher_round_rect.png']:
  path = '/usr/share/unity/6/' + name
  expected = (os.path.expanduser('~/.themes/') + theme + '/unity-shell/' + name
              if theme.startswith('Unity-Focus-') else path)
  content = open(expected, 'rb').read()
  for symbol in ['fopen', 'fopen64']:
   load = getattr(api, symbol)
   load.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
   load.restype = ctypes.c_void_p
   stream = load(path, 'rb')
   assert stream
   buffer = ctypes.create_string_buffer(len(content) + 1)
   size = api.fread(buffer, 1, len(buffer), stream)
   api.fclose(stream)
   assert buffer.raw[:size] == content, (theme, name, symbol)
  actual = GdkPixbuf.Pixbuf.new_from_file(path)
  wanted = GdkPixbuf.Pixbuf.new_from_file(expected)
  assert actual.get_pixels() == wanted.get_pixels(), (theme, name, 'pixbuf')
print('PASS: shell PNG loaders follow accent changes and restore original artwork')
"""
subprocess.run([runtime, '/usr/bin/env', 'LD_PRELOAD=' + config['shellFocus'],
                '/usr/bin/python2.7', '-c', shell_probe,
                first.strip("'"), second.strip("'"), 'Ambiance-Dark'], check=True)

setting('set', 'org.gnome.desktop.interface', 'gtk-theme', 'Radiance')
wait_for(lambda: 'Unity-Focus-Radiance-' in setting('get', 'org.gnome.desktop.interface', 'gtk-theme'))
toggle(False)
wait_for(lambda: setting('get', 'org.gnome.desktop.interface', 'gtk-theme') == "'Radiance'")
assert setting('get', 'org.gnome.desktop.interface', 'icon-theme') == "'ubuntu-mono-dark'"
wait_for(lambda: setting('get', 'org.gnome.desktop.wm.preferences', 'theme') == "'Radiance'")
print('PASS: wallpaper updates, theme switching and theme/icon restoration')

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
import ctypes, sys, time
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
row = [w for w in box.get_children() if w.get_name() == 'unity-dynamic-focus-row'][0]
buttons = [w for w in row.get_children() if w.get_name() == 'unity-dynamic-focus-color']
assert len(buttons) == 1
button = buttons[0]
assert not button.get_active()
scale = [w for w in row.get_children() if w.get_name() == 'unity-focus-brightness'][0]
assert scale.get_value() == 100
assert not scale.get_sensitive()
button.set_active(True)
assert display.load()['dynamicFocus'] is True
assert scale.get_sensitive()
scale.set_value(65)
deadline = time.time() + 3
while display.load()['focusBrightness'] != 65 and time.time() < deadline:
 while Gtk.events_pending(): Gtk.main_iteration()
 time.sleep(.02)
assert display.load()['focusBrightness'] == 65
button.set_active(False)
assert display.load()['dynamicFocus'] is False
assert not scale.get_sensitive()
assert display.load()['focusBrightness'] == 65
assert get_object(hash(builder), 'background-panel')
assert len([w for w in box.get_children() if w.get_name() == 'unity-dynamic-focus-row']) == 1
app = display.Settings()
app.register(None)
app.do_activate()
assert not hasattr(app, 'dynamic_focus')
app.brightness.set_value(80)
assert display.load()['focusBrightness'] == 65
scale.set_value(70)
row.destroy()
assert display.load()['focusBrightness'] == 70
print('PASS: native Appearance toggle persists both states; Display Settings has no duplicate')
''' % str(package / 'libexec/unity-quantal')
subprocess.run([runtime, '/usr/bin/env', 'LD_PRELOAD=' + config['appearanceFocus'],
                'UNITY_FOCUS_SETTINGS=' + str(package / 'libexec/unity-quantal/display.py'),
                '/usr/bin/python2.7', '-c', ui_probe], check=True)
