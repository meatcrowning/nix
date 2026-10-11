"""Expose compatible MPRIS players to Unity without sharing a private app bus."""
import json
import os
from pathlib import Path
import signal
from urllib.parse import quote, unquote

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / 'config.json').read_text())
os.environ['GI_TYPELIB_PATH'] = CONFIG['typelibs']
from gi.repository import Gio, GLib

OBJECT = '/org/mpris/MediaPlayer2'
ROOT = 'org.mpris.MediaPlayer2'
PLAYER = ROOT + '.Player'
PROPERTIES = 'org.freedesktop.DBus.Properties'
# Quantal matches disappearing bus names to desktop IDs by taking the final
# dot component and the part before its first hyphen. Keep those keys aligned.
NAMES = {'rhythmbox': ROOT + '.unity-rhythmbox', 'vivaldi': ROOT + '.vivaldi-unity'}
XML = '''<node><interface name="org.mpris.MediaPlayer2">
<method name="Raise"/><method name="Quit"/>
<property name="CanQuit" type="b" access="read"/>
<property name="CanRaise" type="b" access="read"/>
<property name="HasTrackList" type="b" access="read"/>
<property name="Identity" type="s" access="read"/>
<property name="DesktopEntry" type="s" access="read"/>
<property name="SupportedUriSchemes" type="as" access="read"/>
<property name="SupportedMimeTypes" type="as" access="read"/>
</interface><interface name="org.mpris.MediaPlayer2.Player">
<method name="Next"/><method name="Previous"/><method name="Pause"/>
<method name="PlayPause"/><method name="Stop"/><method name="Play"/>
<method name="Seek"><arg type="x" direction="in"/></method>
<method name="SetPosition"><arg type="o" direction="in"/><arg type="x" direction="in"/></method>
<signal name="Seeked"><arg type="x"/></signal>
<property name="PlaybackStatus" type="s" access="read"/>
<property name="LoopStatus" type="s" access="readwrite"/>
<property name="Rate" type="d" access="readwrite"/>
<property name="Shuffle" type="b" access="readwrite"/>
<property name="Metadata" type="a{sv}" access="read"/>
<property name="Volume" type="d" access="readwrite"/>
<property name="Position" type="x" access="read"/>
<property name="MinimumRate" type="d" access="read"/>
<property name="MaximumRate" type="d" access="read"/>
<property name="CanGoNext" type="b" access="read"/>
<property name="CanGoPrevious" type="b" access="read"/>
<property name="CanPlay" type="b" access="read"/>
<property name="CanPause" type="b" access="read"/>
<property name="CanSeek" type="b" access="read"/>
<property name="CanControl" type="b" access="read"/>
</interface></node>'''
INFO = Gio.DBusNodeInfo.new_for_xml(XML)


def variants(dictionary):
    return {entry.get_child_value(0).get_string(): entry.get_child_value(1).get_variant()
            for entry in (dictionary.get_child_value(i) for i in range(dictionary.n_children()))}


def private_rhythmbox():
    # Match the profile owner's transport, not another user's or a test player.
    base = Path.home() / '.local/state/unity-quantal/isolated'
    try:
        run = (base / 'rhythmbox.lock').read_text().strip()
        if not run.startswith('rhythmbox-') or Path(run).name != run:
            return None
        transport = (base / run / 'transport').stat()
        for process in Path('/proc').iterdir():
            if not process.name.isdigit():
                continue
            try:
                if process.stat().st_uid != os.getuid():
                    continue
                argv = (process / 'cmdline').read_bytes().split(b'\0')
                if not any(argv[i:i+3] == [b'/runner/isolated.py', b'media-worker', b'rhythmbox']
                           for i in range(len(argv))):
                    continue
                mounted = (process / 'root/transport').stat()
                if (mounted.st_dev, mounted.st_ino) != (transport.st_dev, transport.st_ino):
                    continue
                env = dict(item.split(b'=', 1) for item in (process / 'environ').read_bytes().split(b'\0') if b'=' in item)
                address = env.get(b'DBUS_SESSION_BUS_ADDRESS', b'').decode()
                if not address.startswith('unix:path=/tmp/'):
                    continue
                socket = process / 'root' / unquote(address[10:].split(',', 1)[0]).lstrip('/')
                if socket.is_socket():
                    return 'unix:path=' + quote(str(socket), safe='/')
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return None


class Proxy:
    def __init__(self, host, source, destination, kind):
        # Each player needs its own connection: MPRIS uses the same object path.
        self.host = Gio.DBusConnection.new_for_address_sync(os.environ['DBUS_SESSION_BUS_ADDRESS'],
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        self.host.set_exit_on_close(False)
        self.source, self.destination, self.kind = source, destination, kind
        self.cache = {ROOT: {}, PLAYER: {}}
        self.registrations = []
        self.owner = None
        self.pending = False
        self.dead = False
        self.subscription = source.signal_subscribe(destination, PLAYER, 'Seeked', OBJECT, None,
            Gio.DBusSignalFlags.NONE, lambda c, s, p, i, n, v: self.host.emit_signal(None, p, i, n, v))
        self.update()

    def normalize(self, interface, values):
        # Chromium implements a subset; provide stable values for the optional
        # properties in the older panel's complete MPRIS property interface.
        defaults = ({'CanQuit': ('b', False), 'CanRaise': ('b', False),
                     'Identity': ('s', self.kind), 'SupportedUriSchemes': ('as', []),
                     'SupportedMimeTypes': ('as', [])} if interface == ROOT else
                    {'LoopStatus': ('s', 'None'), 'Rate': ('d', 1.), 'Shuffle': ('b', False),
                     'Volume': ('d', 1.), 'Position': ('x', 0), 'MinimumRate': ('d', 1.),
                     'MaximumRate': ('d', 1.), 'Metadata': ('a{sv}', {}), 'PlaybackStatus': ('s', 'Stopped'),
                     **{k: ('b', False) for k in ['CanGoNext', 'CanGoPrevious', 'CanPlay', 'CanPause', 'CanSeek', 'CanControl']}})
        values = {**{k: GLib.Variant(*v) for k, v in defaults.items()}, **values}
        if interface == ROOT:
            values['DesktopEntry'] = GLib.Variant('s', 'unity-original-rhythmbox' if self.kind == 'rhythmbox' else 'vivaldi-stable')
            values['HasTrackList'] = GLib.Variant('b', False)
        elif self.kind == 'rhythmbox' and 'Metadata' in values:
            metadata = variants(values['Metadata'])
            # Rhythmbox's cache lives in its shared profile, under another HOME.
            art = metadata.get('mpris:artUrl')
            if art and art.get_string().startswith('file:///home/legacy/'):
                profile = Path.home() / '.local/state/unity-quantal/isolated/rhythmbox-profile'
                image = (profile / unquote(art.get_string()[20:])).resolve()
                if image.is_relative_to(profile.resolve()) and image.is_file():
                    metadata['mpris:artUrl'] = GLib.Variant('s', image.as_uri())
                else:
                    metadata.pop('mpris:artUrl', None)
            values['Metadata'] = GLib.Variant('a{sv}', metadata)
        return values

    def update(self):
        if self.pending or self.dead:
            return
        self.pending = True
        self.remaining = 2
        for interface in (ROOT, PLAYER):
            self.source.call(self.destination, OBJECT, PROPERTIES, 'GetAll', GLib.Variant('(s)', (interface,)),
                GLib.VariantType.new('(a{sv})'), Gio.DBusCallFlags.NONE, 2000, None, self.received, interface)

    def received(self, connection, result, interface):
        if self.dead:
            return
        try:
            values = self.normalize(interface, variants(connection.call_finish(result).get_child_value(0)))
            changed = {k: v for k, v in values.items() if k not in self.cache[interface] or not v.equal(self.cache[interface][k])}
            self.cache[interface] = values
            if self.owner and changed:
                self.host.emit_signal(None, OBJECT, PROPERTIES, 'PropertiesChanged', GLib.Variant('(sa{sv}as)', (interface, changed, [])))
        except GLib.Error:
            self.dead = True
        self.remaining -= 1
        if self.remaining:
            return
        self.pending = False
        if not self.dead and not self.owner:
            self.registrations = [self.host.register_object(OBJECT, info, self.call, self.get, self.set) for info in INFO.interfaces]
            self.owner = Gio.bus_own_name_on_connection(self.host, NAMES[self.kind],
                Gio.BusNameOwnerFlags.NONE, None, None)

    def get(self, connection, sender, path, interface, property):
        return self.cache[interface].get(property)

    def set(self, connection, sender, path, interface, property, value):
        # Only the four writable Player properties declared above reach here.
        self.source.call(self.destination, OBJECT, PROPERTIES, 'Set', GLib.Variant('(ssv)', (interface, property, value)),
            None, Gio.DBusCallFlags.NONE, 2000, None, self.set_done)
        return True

    def set_done(self, connection, result):
        try:
            connection.call_finish(result)
        except GLib.Error as error:
            print('MPRIS property update:', error, flush=True)

    def call(self, connection, sender, path, interface, method, parameters, invocation):
        # register_object limits requests to the declared media methods. No
        # arbitrary objects, names, activation or file-opening API is exposed.
        self.source.call(self.destination, OBJECT, interface, method, parameters, None,
            Gio.DBusCallFlags.NONE, 3000, None, self.replied, invocation)

    def replied(self, connection, result, invocation):
        try:
            invocation.return_value(connection.call_finish(result))
            self.update()
        except GLib.Error as error:
            invocation.return_dbus_error(ROOT + '.Error.Failed', str(error))

    def close(self):
        self.dead = True
        if self.owner:
            Gio.bus_unown_name(self.owner)
        for registration in self.registrations:
            self.host.unregister_object(registration)
        self.source.signal_unsubscribe(self.subscription)
        self.host.close_sync(None)
        if self.kind == 'rhythmbox':
            self.source.close_sync(None)


class Bridge:
    def __init__(self, host):
        self.host = host
        self.proxies = {}
        self.scanning = False

    def tick(self):
        for kind, proxy in list(self.proxies.items()):
            if proxy.dead:
                proxy.close()
                del self.proxies[kind]
            else:
                proxy.update()
        if not self.scanning:
            self.scanning = True
            self.host.call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'ListNames',
                None, None, Gio.DBusCallFlags.NONE, 2000, None, self.names)
        return True

    def names(self, connection, result):
        self.scanning = False
        try:
            names = connection.call_finish(result).unpack()[0]
            if 'vivaldi' not in self.proxies:
                name = next((n for n in names if n.startswith(ROOT + '.vivaldi') and n != NAMES['vivaldi']), None)
                if name:
                    self.proxies['vivaldi'] = Proxy(self.host, self.host, name, 'vivaldi')
            if 'rhythmbox' not in self.proxies:
                address = private_rhythmbox()
                if address:
                    source = Gio.DBusConnection.new_for_address_sync(address,
                        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
                    source.set_exit_on_close(False)
                    self.proxies['rhythmbox'] = Proxy(self.host, source, ROOT + '.rhythmbox', 'rhythmbox')
        except GLib.Error as error:
            print('MPRIS discovery:', error, flush=True)


def main():
    loop = GLib.MainLoop()
    host = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    owner = Gio.bus_own_name_on_connection(host, 'org.unity_quantal.Media', Gio.BusNameOwnerFlags.NONE,
        None, lambda *_: loop.quit())
    bridge = Bridge(host)
    bridge.tick()
    GLib.timeout_add_seconds(2, bridge.tick)
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (loop.quit(), False)[1])
    try:
        loop.run()
    finally:
        for proxy in bridge.proxies.values():
            proxy.close()
        Gio.bus_unown_name(owner)


if __name__ == '__main__':
    main()
