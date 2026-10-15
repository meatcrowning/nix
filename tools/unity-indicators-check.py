"""Run only inside unity-quantal-test.sh's private display, bus and home."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

package = Path(os.environ['UNITY_PACKAGE'])
sys.path.insert(0, str(package / 'libexec/unity-quantal'))
import media
from gi.repository import Gio, GLib

config = media.CONFIG
context = GLib.MainContext.default()


def wait_for(predicate, description):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError(description)


def call(destination, path, method, *args, success=True):
    process = subprocess.Popen([config['gdbus'], 'call', '--session', '--dest', destination,
        '--object-path', path, '--method', method, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    wait_for(lambda: process.poll() is not None, method)
    stdout, stderr = process.communicate()
    if success:
        assert process.returncode == 0, stderr
        return GLib.Variant.parse(None, stdout.strip(), None, None).unpack()
    assert process.returncode != 0


class FakePlayer:
    def __init__(self, connection, name):
        self.calls = []
        label = 'Vivaldi' if 'vivaldi' in name else 'Rhythmbox'
        self.values = {media.ROOT: {'CanQuit': GLib.Variant('b', True), 'CanRaise': GLib.Variant('b', True),
            'HasTrackList': GLib.Variant('b', False), 'Identity': GLib.Variant('s', label),
            'SupportedUriSchemes': GLib.Variant('as', []), 'SupportedMimeTypes': GLib.Variant('as', [])},
            media.PLAYER: {'PlaybackStatus': GLib.Variant('s', 'Paused'),
                'Metadata': GLib.Variant('a{sv}', {'xesam:title': GLib.Variant('s', label + ' probe'),
                    'xesam:artist': GLib.Variant('as', ['Test artist'])}),
                'LoopStatus': GLib.Variant('s', 'None'), 'Rate': GLib.Variant('d', 1.),
                'Volume': GLib.Variant('d', .5), 'Shuffle': GLib.Variant('b', False),
                'Position': GLib.Variant('x', 0), 'MinimumRate': GLib.Variant('d', 1.),
                'MaximumRate': GLib.Variant('d', 1.),
                **{k: GLib.Variant('b', True) for k in ['CanGoNext', 'CanGoPrevious', 'CanPlay', 'CanPause', 'CanSeek', 'CanControl']}}}
        xml = media.XML.replace('<property name="DesktopEntry" type="s" access="read"/>', '')
        self.registrations = [connection.register_object(media.OBJECT, info, self.method,
            lambda c, s, p, i, k: self.values[i][k], self.set) for info in Gio.DBusNodeInfo.new_for_xml(xml).interfaces]
        self.owner = Gio.bus_own_name_on_connection(connection, name, Gio.BusNameOwnerFlags.NONE, None, None)

    def method(self, c, s, p, interface, name, parameters, invocation):
        self.calls.append(name)
        if name == 'PlayPause':
            self.values[media.PLAYER]['PlaybackStatus'] = GLib.Variant('s', 'Playing')
        invocation.return_value(GLib.Variant('()', ()))

    def set(self, c, s, p, interface, name, value):
        self.values[interface][name] = value
        return True


host = Gio.bus_get_sync(Gio.BusType.SESSION, None)
vivaldi = FakePlayer(host, media.ROOT + '.vivaldi.instance123')
wait_for(lambda: call('org.freedesktop.DBus', '/org/freedesktop/DBus',
    'org.freedesktop.DBus.NameHasOwner', media.NAMES['vivaldi'])[0], 'Vivaldi discovery')
entry = call(media.NAMES['vivaldi'], media.OBJECT, media.PROPERTIES + '.Get', media.ROOT, 'DesktopEntry')[0]
assert entry == 'vivaldi-stable', entry
call(media.NAMES['vivaldi'], media.OBJECT, media.PLAYER + '.PlayPause')
assert vivaldi.calls == ['PlayPause'], vivaldi.calls

# A second private bus reproduces Rhythmbox's boundary. The bridge publishes
# only the MPRIS object; there is no shared bus or generic call forwarding.
private_config = Path(os.environ['XDG_RUNTIME_DIR']) / 'mpris-private.conf'
private_config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen><auth>EXTERNAL</auth>'
    '<policy context="default"><allow send_destination="*"/><allow receive_sender="*"/><allow own="*"/></policy></busconfig>')
daemon = subprocess.Popen([config['dbus'], '--config-file=' + str(private_config), '--nofork', '--print-address=1'],
    stdout=subprocess.PIPE, text=True)
address = daemon.stdout.readline().strip()
private = Gio.DBusConnection.new_for_address_sync(address,
    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
private.set_exit_on_close(False)
rhythmbox = FakePlayer(private, media.ROOT + '.rhythmbox')
proxy = None
try:
    wait_for(lambda: private.get_unique_name() is not None, 'private bus connection')
    proxy = media.Proxy(host, private, media.ROOT + '.rhythmbox', 'rhythmbox')
    wait_for(lambda: proxy.owner is not None, 'Rhythmbox proxy registration')
    wait_for(lambda: call('org.freedesktop.DBus', '/org/freedesktop/DBus',
        'org.freedesktop.DBus.NameHasOwner', media.NAMES['rhythmbox'])[0], 'Rhythmbox bus name')
    assert call(media.NAMES['rhythmbox'], media.OBJECT, media.PROPERTIES + '.Get', media.ROOT, 'DesktopEntry')[0] == 'unity-original-rhythmbox'
    call(media.NAMES['rhythmbox'], media.OBJECT, media.PLAYER + '.Next')
    call(media.NAMES['rhythmbox'], media.OBJECT, media.PLAYER + '.PlayPause')
    assert rhythmbox.calls == ['Next', 'PlayPause'], rhythmbox.calls
    call(media.NAMES['rhythmbox'], media.OBJECT, media.PLAYER + '.OpenUri', 'file:///etc/passwd', success=False)
    call(media.NAMES['rhythmbox'], '/org/freedesktop/DBus', 'org.freedesktop.DBus.ListNames', success=False)
    metadata = call(media.NAMES['rhythmbox'], media.OBJECT, media.PROPERTIES + '.Get', media.PLAYER, 'Metadata')[0]
    assert metadata['xesam:title'].endswith('probe')
    # Verify the actual old sound menu recognizes both normalized identities.
    def players_present():
        layout = call('com.canonical.indicator.sound', '/com/canonical/indicator/sound/menu',
                      'com.canonical.dbusmenu.GetLayout', '--', '0', '-1', '[]')
        text = str(layout)
        return 'Vivaldi probe' in text and 'Rhythmbox probe' in text
    wait_for(players_present, 'players in original indicator-sound menu')
    # Metadata and playback changes must reach the old menu after discovery.
    rhythmbox.values[media.PLAYER]['Metadata'] = GLib.Variant('a{sv}', {'xesam:title': GLib.Variant('s', 'Updated track')})
    proxy.update()
    wait_for(lambda: 'Updated track' in str(call('com.canonical.indicator.sound', '/com/canonical/indicator/sound/menu',
        'com.canonical.dbusmenu.GetLayout', '--', '0', '-1', '[]')), 'track update in old menu')
    print('PASS: old sound menu, two simultaneous MPRIS players, controls, metadata and restricted private-bus proxy', flush=True)
finally:
    if proxy:
        proxy.close()
    daemon.terminate()
    daemon.wait(timeout=5)

def offline():
    layout = call('com.canonical.indicator.sound', '/com/canonical/indicator/sound/menu',
                  'com.canonical.dbusmenu.GetLayout', '--', '0', '-1', '[]')
    for _, props, _ in layout[1][2]:
        if props.get('x-canonical-sound-menu-player-metadata-player-name') == 'Rhythmbox':
            return props.get('x-canonical-sound-menu-player-metadata-player-running') is False
    return False
wait_for(offline, 'closed player marked offline in old sound menu')

for name in ['org.unity_quantal.Gpu', 'org.unity_quantal.Load', 'org.unity_quantal.Temperature', 'org.unity_quantal.NotificationIndicator']:
    wait_for(lambda name=name: call('org.freedesktop.DBus', '/org/freedesktop/DBus',
        'org.freedesktop.DBus.NameHasOwner', name)[0], name)
panel = call('com.canonical.Unity.Panel.Service', '/com/canonical/Unity/Panel/Service',
    'com.canonical.Unity.Panel.Service.Sync')[0]
for name in ['unity-quantal-gpu', 'unity-quantal-load', 'unity-quantal-temperature']:
    assert any(row[2] == name and row[8] and row[9] for row in panel), (name, panel)

def notification_visible():
    rows = call('com.canonical.Unity.Panel.Service', '/com/canonical/Unity/Panel/Service',
                'com.canonical.Unity.Panel.Service.Sync')[0]
    return any(row[2] == 'unity-quantal-notifications' and row[8] and row[9] for row in rows)
wait_for(notification_visible, 'empty notification history remains visible')
assert not Path(os.environ['UNITY_QUANTAL_SESSION_DIR'], 'autostart/unity-quantal-cpufreq.desktop').exists()

applications = call('com.canonical.indicator.application', '/com/canonical/indicator/application/service',
                    'com.canonical.indicator.application.service.GetApplications')[0]
meters = [row for row in applications if row[-1] in ['System Load', 'GPU Load', 'Temperatures']]
assert len(meters) == 3, applications
gpu = next(row for row in applications if row[-1] == 'GPU Load')
cpu = next(row for row in applications if row[-1] == 'System Load')
assert gpu[1] == cpu[1] + 1, ('GPU must immediately follow CPU', applications)
def gpu_menu():
    return str(call(gpu[2], gpu[3], 'com.canonical.dbusmenu.GetLayout', '--', '0', '-1', '[]'))
wait_for(lambda: 'GPU: 63%' in gpu_menu() and 'VRAM: 2.0 / 8.0 GiB' in gpu_menu(), 'GPU telemetry')
Path.home().joinpath('gpu-reading').write_text('Test GPU, 81, 4096, 8192, 52\n')
wait_for(lambda: 'GPU: 81%' in gpu_menu() and 'VRAM: 4.0 / 8.0 GiB' in gpu_menu(), 'GPU telemetry update')
icons = list(Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))).rglob('gpu-*.svg'))
assert icons and 'stroke-dasharray="1 2"' in icons[-1].read_text(), icons
assert not any(row[8] == 'unity-quantal-cpufreq' for row in applications), applications
# This is the harness's private system bus; profile changes cannot reach top.
profile_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
profile_values = {'ActiveProfile': GLib.Variant('s', 'balanced'),
    'Profiles': GLib.Variant('aa{sv}', [{'Profile': GLib.Variant('s', name)}
        for name in ('performance', 'balanced', 'power-saver')]),
    'PerformanceDegraded': GLib.Variant('s', '')}
profile_info = Gio.DBusNodeInfo.new_for_xml('<node><interface name="net.hadess.PowerProfiles">'
    '<property name="ActiveProfile" type="s" access="readwrite"/>'
    '<property name="Profiles" type="aa{sv}" access="read"/>'
    '<property name="PerformanceDegraded" type="s" access="read"/>'
    '</interface></node>').interfaces[0]
def set_profile(c, sender, path, interface, name, value):
    profile_values[name] = value
    c.emit_signal(None, path, 'org.freedesktop.DBus.Properties', 'PropertiesChanged',
        GLib.Variant('(sa{sv}as)', (interface, {name: value}, [])))
    return True
profile_registration = profile_bus.register_object('/net/hadess/PowerProfiles', profile_info, None,
    lambda c, s, p, i, name: profile_values[name], set_profile)
profile_owner = Gio.bus_own_name_on_connection(profile_bus, 'net.hadess.PowerProfiles',
    Gio.BusNameOwnerFlags.NONE, None, None)
def cpu_layout():
    return call(cpu[2], cpu[3], 'com.canonical.dbusmenu.GetLayout', '--', '0', '-1', '[]')[1][2]
def selected(label):
    return any(props.get('label') == label and props.get('toggle-state') == 1
               and props.get('enabled', True) for _, props, _ in cpu_layout())
wait_for(lambda: selected('Balanced'), 'profile daemon discovered by combined CPU menu')
performance = next(id for id, props, _ in cpu_layout() if props.get('label') == 'Performance')
call(cpu[2], cpu[3], 'com.canonical.dbusmenu.Event', str(performance), 'clicked', '<int32 0>', '0')
wait_for(lambda: profile_values['ActiveProfile'].unpack() == 'performance' and selected('Performance'),
         'combined CPU menu changes the private daemon profile')
cpu_menu = str(cpu_layout())
for label in ['Average:', 'Fastest core:', 'Performance', 'Balanced', 'Power Saver']:
    assert label in cpu_menu, (label, cpu_menu)

def menu_ids(row):
    layout = call(row[2], row[3], 'com.canonical.dbusmenu.GetLayout', '--', '0', '-1', '[]')
    return [item[0] for item in layout[1][2]]
before = [menu_ids(row) for row in meters]
deadline = time.monotonic() + 3
wait_for(lambda: time.monotonic() >= deadline, 'meter update')
assert [menu_ids(row) for row in meters] == before, 'meter refresh replaced open menu items'
Path.home().joinpath('gpu-reading').unlink()
wait_for(lambda: 'GPU readings unavailable' in gpu_menu(), 'failed GPU read shown as unavailable')

history = Path(os.environ['UNITY_QUANTAL_SESSION_DIR']) / 'notification-history.json'
notification_id = call('org.freedesktop.Notifications', '/org/freedesktop/Notifications',
    'org.freedesktop.Notifications.Notify', 'Indicator probe', '0', '', 'History probe', 'Test body',
    '[]', "{'suppress-sound': <true>}", '1000')[0]
wait_for(lambda: history.exists() and any(e['id'] == notification_id for e in json.loads(history.read_text())), 'notification recording')
assert history.stat().st_mode & 0o777 == 0o600
assert json.loads(history.read_text())[-1]['body'] == 'Test body'
wait_for(notification_visible, 'nonempty notification history appears')
call('org.freedesktop.Notifications', '/org/freedesktop/Notifications', 'org.freedesktop.Notifications.Notify',
    'Indicator probe', '0', '', 'Transient probe', '', '[]', "{'transient': <true>, 'suppress-sound': <true>}", '1000')
assert not any(e['summary'] == 'Transient probe' for e in json.loads(history.read_text()))
call('org.freedesktop.Notifications', '/org/unity_quantal/NotificationHistory', 'org.unity_quantal.NotificationHistory.Clear')
assert json.loads(history.read_text()) == []
notifications = next(row for row in applications if row[-1] == 'Recent Notifications')
wait_for(lambda: 'No recent notifications' in str(call(notifications[2], notifications[3],
    'com.canonical.dbusmenu.GetLayout', '--', '0', '-1', '[]')), 'cleared notification menu')
assert notification_visible(), 'clearing notification history must keep the icon visible'
print('PASS: CPU/GPU order, GPU readings and graph, all panel entries, stable meter menus; private session history, transient exclusion and clear', flush=True)
