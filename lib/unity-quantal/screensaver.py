"""Translate Unity 6's screen-lock API to the current Cinnamon locker."""

from gi.repository import Gio, GLib

LEGACY = "org.gnome.ScreenSaver"
CURRENT = "org.cinnamon.ScreenSaver"
PATH = "/org/gnome/ScreenSaver"
INFO = Gio.DBusNodeInfo.new_for_xml("""
<node><interface name="org.gnome.ScreenSaver">
  <method name="Lock"/>
  <method name="GetActive"><arg type="b" direction="out"/></method>
  <method name="GetActiveTime"><arg type="u" direction="out"/></method>
  <method name="SimulateUserActivity"/>
  <signal name="ActiveChanged"><arg type="b"/></signal>
</interface></node>
""")


def method(connection, sender, path, interface, name, parameters, invocation):
    def completed(bus, result):
        try:
            invocation.return_value(bus.call_finish(result))
        except GLib.Error as error:
            invocation.return_dbus_error(LEGACY + ".Error", str(error))

    # A successful reply must mean the native locker has finished locking.
    if name == "Lock":
        parameters = GLib.Variant("(s)", ("",))
    connection.call(CURRENT, "/org/cinnamon/ScreenSaver", CURRENT, name,
                    parameters, None, Gio.DBusCallFlags.NONE, 30000, None, completed)


def acquired(connection, name):
    connection.register_object(PATH, INFO.interfaces[0], method, None, None)

    def changed(bus, sender, path, interface, signal, parameters):
        bus.emit_signal(None, PATH, LEGACY, signal, parameters)

    connection.signal_subscribe(CURRENT, CURRENT, "ActiveChanged",
                                "/org/cinnamon/ScreenSaver", None,
                                Gio.DBusSignalFlags.NONE, changed)


loop = GLib.MainLoop()
owner = Gio.bus_own_name(Gio.BusType.SESSION, LEGACY, Gio.BusNameOwnerFlags.NONE,
                         acquired, None, lambda *_: loop.quit())
loop.run()
