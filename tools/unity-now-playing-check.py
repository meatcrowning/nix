"""Only run inside unity-quantal-test.sh's private display, bus and home."""
import base64
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(os.environ['UNITY_PACKAGE']) / 'libexec/unity-quantal'))
import media
from gi.repository import Gio, GLib

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
context = GLib.MainContext.default()


def wait(predicate, message, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        value = predicate()
        if value:
            return value
        time.sleep(.04)
    raise AssertionError(message)


def call(method, *args):
    p = subprocess.Popen([media.CONFIG['gdbus'], 'call', '--session', '--dest',
        'com.canonical.Unity.Panel.Service', '--object-path', '/com/canonical/Unity/Panel/Service',
        '--method', 'com.canonical.Unity.Panel.Service.' + method, *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # Sync includes base64 PNGs, so drain pipes without blocking the fake player.
    while True:
        while context.pending():
            context.iteration(False)
        try:
            out, err = p.communicate(timeout=.05)
            break
        except subprocess.TimeoutExpired:
            continue
    assert p.returncode == 0, err
    return GLib.Variant.parse(None, out.strip(), None, None).unpack()


def entry():
    return next((r for r in call('Sync')[0] if r[0] == 'libnowplaying.so' and r[1]), None)


def pixels(row):
    png = base64.b64decode(row[7])
    dimensions = subprocess.check_output(['magick', 'png:-', '-format', '%w %h', 'info:'], input=png)
    data = subprocess.check_output(['magick', 'png:-', '-depth', '8', 'rgba:-'], input=png)
    return (*map(int, dimensions.split()), data)


assert not entry(), 'Music entry must be absent without custom Rhythmbox'
art = Path.home() / 'cover.png'
subprocess.run(['magick', '-size', '22x22', 'xc:red', str(art)], check=True)
metadata = {'xesam:title': GLib.Variant('s', 'A long track title with café and 日本語 that needs scrolling across the panel'),
            'xesam:artist': GLib.Variant('as', ['First artist', 'Second artist']),
            'mpris:artUrl': GLib.Variant('s', art.as_uri())}
props = {'Metadata': GLib.Variant('a{sv}', metadata), 'PlaybackStatus': GLib.Variant('s', 'Paused')}
info = Gio.DBusNodeInfo.new_for_xml('''<node><interface name="org.mpris.MediaPlayer2.Player">
<property name="Metadata" type="a{sv}" access="read"/>
<property name="PlaybackStatus" type="s" access="read"/>
</interface></node>''')
registration = bus.register_object(media.OBJECT, info.interfaces[0], None,
    lambda c, s, p, i, name: props[name], None)
owner = Gio.bus_own_name_on_connection(bus, media.NAMES['rhythmbox'], Gio.BusNameOwnerFlags.NONE, None, None)
row = wait(entry, 'Music indicator did not appear')
Path('/work/music-idle.png').write_bytes(base64.b64decode(row[7]))
image = pixels(row)
assert image[:2] == (248, 22)
data = image[2]
assert data[10*248*4+10*4:10*248*4+10*4+3] == b'\xff\x00\x00', 'Cover not rendered'
priorities = {r[0]: r[-1] for r in call('Sync')[0] if r[1]}
assert priorities['libnowplaying.so'] < priorities['libsoundmenu.so']
assert not any(priorities['libnowplaying.so'] < p < priorities['libsoundmenu.so'] for p in priorities.values())
print('PASS: cover, fixed dimensions, paused-player visibility, immediately left of volume')

# Give the entry an isolated test rectangle; never move the host pointer.
call('SyncGeometries', repr([('music-probe', row[1], 500, 500, 248, 22)]))
subprocess.run(['xdotool', 'mousemove', '501', '501'], check=True)
initial = row[7]
scrolled = wait(lambda: (r if (r := entry()) and r[7] != initial else None), 'Hover did not scroll')
Path('/work/music-hover.png').write_bytes(base64.b64decode(scrolled[7]))
assert pixels(scrolled)[:2] == (248, 22)
wait(lambda: entry()[7] != scrolled[7], 'Hovered text did not continue moving')
subprocess.run(['xdotool', 'mousemove', '500', '600'], check=True)
wait(lambda: entry()[7] == initial, 'Pointer leave did not restore ellipsis')
print('PASS: hover changes rendered text without resizing; leaving restores it')

metadata['xesam:title'] = GLib.Variant('s', 'Short')
metadata['xesam:artist'] = GLib.Variant('as', ['Artist'])
metadata['mpris:artUrl'] = GLib.Variant('s', 'file:///missing-cover.png')
props['Metadata'] = GLib.Variant('a{sv}', metadata)
bus.emit_signal(None, media.OBJECT, media.PROPERTIES, 'PropertiesChanged',
    GLib.Variant('(sa{sv}as)', (media.PLAYER, props, [])))
short = wait(lambda: (r if (r := entry()) and r[7] != initial else None), 'Track did not update')
short_width, short_height, short_data = pixels(short)
assert 28 < short_width < 248 and short_height == 22, 'Short text kept the maximum width'
last_ink = max(x for y in range(short_height) for x in range(short_width)
               if short_data[(y * short_width + x) * 4 + 3])
assert short_width - last_ink <= 4, 'Unused space remains after the text'
metadata['xesam:artist'] = GLib.Variant('as', ['A different artist with a very long name'])
props['Metadata'] = GLib.Variant('a{sv}', metadata)
bus.emit_signal(None, media.OBJECT, media.PROPERTIES, 'PropertiesChanged',
    GLib.Variant('(sa{sv}as)', (media.PLAYER, props, [])))
subprocess.run(['xdotool', 'mousemove', '501', '501'], check=True)
end = time.monotonic() + 2
while time.monotonic() < end:
    assert entry()[7] == short[7], 'Artist changes or hover altered the short track title'
    time.sleep(.1)
print('PASS: track changes, missing-art fallback and short-text hover')
Gio.bus_unown_name(owner)
wait(lambda: not entry(), 'Music entry stayed visible after player exit')
print('PASS: entry disappears when Rhythmbox closes')
owner = Gio.bus_own_name_on_connection(bus, media.NAMES['rhythmbox'], Gio.BusNameOwnerFlags.NONE, None, None)
wait(entry, 'Music entry did not return after player restart')
Gio.bus_unown_name(owner)
wait(lambda: not entry(), 'Restarted player did not hide')
print('PASS: player restart restores the entry')

bus.unregister_object(registration)
