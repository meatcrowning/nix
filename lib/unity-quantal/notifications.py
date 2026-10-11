"""Chromium compatibility for Quantal's non-interactive native bubbles.

Chromium refuses a server without the actions capability. Accept its action
array, but deliberately present the passive Ubuntu bubble: no fabricated click
or action signals. Notify OSD otherwise turns action requests into dialogs.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / 'config.json').read_text())
os.environ['GI_TYPELIB_PATH'] = CONFIG['typelibs']
import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib
from sounds import Player
NAME = 'org.freedesktop.Notifications'
OBJECT = '/org/freedesktop/Notifications'
XML = '''<node><interface name="org.freedesktop.Notifications">
<method name="GetCapabilities"><arg type="as" direction="out"/></method>
<method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/></method>
<method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/><arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
<method name="CloseNotification"><arg type="u" direction="in"/></method>
<signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
<signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
</interface></node>'''


class Adapter:
    def __init__(self, upstream, native):
        self.upstream, self.native = upstream, native
        self.player = Player()
        self.history_path = Path(os.environ['UNITY_QUANTAL_SESSION_DIR']) / 'notification-history.json'
        self.history_registration = upstream.register_object('/org/unity_quantal/NotificationHistory',
            Gio.DBusNodeInfo.new_for_xml('<node><interface name="org.unity_quantal.NotificationHistory">'
                '<method name="Clear"/></interface></node>').interfaces[0], self.clear_history, None, None)
        self.registration = upstream.register_object(
            OBJECT, Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], self.call, None, None)
        # Preserve Notify OSD's lock-screen suppression on its private bus.
        self.saver_registration = native.register_object('/org/gnome/ScreenSaver',
            Gio.DBusNodeInfo.new_for_xml('<node><interface name="org.gnome.ScreenSaver">'
                '<method name="GetActive"><arg type="b" direction="out"/></method>'
                '<signal name="ActiveChanged"><arg type="b"/></signal>'
                '</interface></node>').interfaces[0], self.saver_call, None, None)
        self.saver_owner = Gio.bus_own_name_on_connection(native, 'org.gnome.ScreenSaver',
                                                         Gio.BusNameOwnerFlags.NONE, None, None)
        self.saver_subscription = upstream.signal_subscribe('org.gnome.ScreenSaver', 'org.gnome.ScreenSaver',
            'ActiveChanged', '/org/gnome/ScreenSaver', None, Gio.DBusSignalFlags.NONE, self.saver_changed)
        self.subscription = native.signal_subscribe(NAME, NAME, 'NotificationClosed', OBJECT, None,
                                                    Gio.DBusSignalFlags.NONE, self.closed)

    def saver_call(self, connection, sender, path, interface, method, parameters, invocation):
        self.upstream.call('org.gnome.ScreenSaver', path, interface, method, parameters, None,
                          Gio.DBusCallFlags.NONE, 3000, None, self.replied, (method, invocation))

    def saver_changed(self, connection, sender, path, interface, name, parameters):
        self.native.emit_signal(None, path, interface, name, parameters)

    def closed(self, connection, sender, path, interface, name, parameters):
        self.upstream.emit_signal(None, OBJECT, NAME, name, parameters)

    def call(self, connection, sender, path, interface, method, parameters, invocation):
        sound = None
        history = None
        if method == 'Notify':
            # Retain variant-valued hints verbatim (not unpack/repack, which
            # loses their D-Bus types). OSD expects passive notifications.
            children = [parameters.get_child_value(i) for i in range(8)]
            hints = children[6].unpack()
            if not hints.get('transient', False) and 'x-canonical-private-synchronous' not in hints:
                history = (children[0].unpack(), children[3].unpack(), children[4].unpack())
            if not hints.get('suppress-sound', False):
                sound = (hints.get('sound-name'), hints.get('sound-file'))
            children[5] = GLib.Variant('as', [])
            children[7] = GLib.Variant('i', -1)
            parameters = GLib.Variant.new_tuple(*children)
        self.native.call(NAME, OBJECT, NAME, method, parameters, None,
                         Gio.DBusCallFlags.NONE, 5000, None, self.replied, (method, invocation, sound, history))

    def write_history(self, entries):
        temporary = self.history_path.with_suffix('.tmp')
        # Contents belong to this session, never the synced configuration.
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(entries[-30:], stream)
        temporary.replace(self.history_path)

    def clear_history(self, connection, sender, path, interface, method, parameters, invocation):
        self.write_history([])
        invocation.return_value(GLib.Variant('()', ()))

    def remember(self, notification_id, entry):
        def unlocked(connection, result):
            try:
                if connection.call_finish(result).unpack()[0]:
                    return
                try:
                    entries = json.loads(self.history_path.read_text())
                except (OSError, ValueError):
                    entries = []
                entries = [old for old in entries if old['id'] != notification_id]
                app, summary, body = entry
                entries.append(dict(id=notification_id, time=time.time(), app=app[:120],
                                    summary=summary[:250], body=body[:2000]))
                self.write_history(entries)
            except (GLib.Error, OSError):
                pass
        self.upstream.call('org.gnome.ScreenSaver', '/org/gnome/ScreenSaver', 'org.gnome.ScreenSaver',
                           'GetActive', None, None, Gio.DBusCallFlags.NONE, 3000, None, unlocked)

    def notification_sound(self, sound):
        event, filename = sound
        if not event and not filename:
            return
        def unlocked(connection, result):
            try:
                if not connection.call_finish(result).unpack()[0]:
                    self.player.play(event or 'message', filename=filename)
            except GLib.Error:
                pass  # A missing lock service must not expose private alerts.
        self.upstream.call('org.gnome.ScreenSaver', '/org/gnome/ScreenSaver', 'org.gnome.ScreenSaver',
                           'GetActive', None, None, Gio.DBusCallFlags.NONE, 3000, None, unlocked)

    def replied(self, connection, result, context):
        method, invocation = context[:2]
        try:
            reply = connection.call_finish(result)
            if method == 'GetCapabilities':
                capabilities = list(reply.unpack()[0])
                if 'actions' not in capabilities:
                    capabilities.append('actions')
                reply = GLib.Variant('(as)', (capabilities,))
            invocation.return_value(reply)
            if method == 'Notify':
                if len(context) > 2 and context[2]:
                    self.notification_sound(context[2])
                if len(context) > 3 and context[3]:
                    self.remember(reply.unpack()[0], context[3])
        except GLib.Error as error:
            invocation.return_dbus_error(NAME + '.Error', str(error))


def main():
    loop = GLib.MainLoop()
    processes = []
    with tempfile.TemporaryDirectory(prefix='unity-notifications-', dir=os.environ['XDG_RUNTIME_DIR']) as directory:
        directory = Path(directory)
        address = 'unix:path=' + str(directory / 'bus')
        config = directory / 'bus.conf'
        config.write_text('<busconfig><type>session</type><listen>' + address + '</listen><auth>EXTERNAL</auth>'
                          '<policy context="default"><allow send_destination="*"/><allow receive_sender="*"/>'
                          '<allow own="*"/></policy></busconfig>')
        try:
            bus = subprocess.Popen([CONFIG['dbus'], '--config-file=' + str(config), '--nofork', '--print-address=1'],
                                   stdout=subprocess.PIPE, text=True)
            processes.append(bus)
            if not bus.stdout.readline().strip().startswith(address):
                raise RuntimeError('Native notification bus failed to start')
            native = Gio.DBusConnection.new_for_address_sync(address,
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
            environment = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address)
            daemon = subprocess.Popen([str(HERE.parent.parent / 'bin/unity-quantal-runtime'),
                                       '/usr/lib/notify-osd/notify-osd'], env=environment)
            processes.append(daemon)
            # Do not claim the public name until the original daemon is ready.
            import time
            for _ in range(100):
                ready = native.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
                    'org.freedesktop.DBus', 'NameHasOwner', GLib.Variant('(s)', (NAME,)),
                    None, Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
                if ready:
                    break
                if daemon.poll() is not None:
                    raise RuntimeError('Notify OSD exited before becoming ready')
                time.sleep(.05)
            else:
                raise RuntimeError('Notify OSD did not become ready')
            upstream = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            adapter = Adapter(upstream, native)
            owner = Gio.bus_own_name_on_connection(upstream, NAME, Gio.BusNameOwnerFlags.NONE,
                                                   None, lambda *_: loop.quit())
            for sig in (signal.SIGINT, signal.SIGTERM):
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (loop.quit(), False)[1])
            def children_alive():
                if any(process.poll() is not None for process in processes):
                    loop.quit()
                    return False
                return True
            GLib.timeout_add_seconds(1, children_alive)
            loop.run()
            Gio.bus_unown_name(owner)
            upstream.unregister_object(adapter.registration)
            adapter.player.close()
            native.close_sync(None)
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    main()
