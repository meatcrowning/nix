"""Ubuntu event playback and session lifecycle on Unity's private bus.

GTK owns widget/dialog sounds; applications own messaging/telephony sounds.
This service owns login/logout and trash, which the native session manager
and Files bridge otherwise leave without a sound producer.
"""
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text())
os.environ["DCONF_PROFILE"] = str(HERE / "dconf-profile")
os.environ["GIO_EXTRA_MODULES"] = CONFIG["dconfModules"]
os.environ["GSETTINGS_BACKEND"] = "dconf"
import gi
from gi.repository import Gio, GLib

NAME = "org.unity_quantal.Sounds"
MANAGER = "org.gnome.SessionManager"
MANAGER_PATH = "/org/gnome/SessionManager"


class VolumeKeys:
    """Forward X11 volume keys which Cinnamon normally forwards from its shell."""
    class KeyEvent(ctypes.Structure):
        _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                    ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("root", ctypes.c_ulong),
                    ("subwindow", ctypes.c_ulong), ("time", ctypes.c_ulong), ("x", ctypes.c_int),
                    ("y", ctypes.c_int), ("x_root", ctypes.c_int), ("y_root", ctypes.c_int),
                    ("state", ctypes.c_uint), ("keycode", ctypes.c_uint), ("same_screen", ctypes.c_int)]

    class Event(ctypes.Union):
        _fields_ = [("pad", ctypes.c_long * 24)]

    def __init__(self, bus, player):
        self.bus, self.player = bus, player
        self.x = ctypes.CDLL(CONFIG["libX11"])
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]; self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]; self.x.XDefaultRootWindow.restype = ctypes.c_ulong
        self.x.XStringToKeysym.argtypes = [ctypes.c_char_p]; self.x.XStringToKeysym.restype = ctypes.c_ulong
        self.x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]; self.x.XKeysymToKeycode.restype = ctypes.c_uint
        self.x.XGrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self.x.XPending.argtypes = [ctypes.c_void_p]
        self.x.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(self.Event)]
        self.x.XFlush.argtypes = [ctypes.c_void_p]
        self.x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.error_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        self.x.XSetErrorHandler.argtypes = [ctypes.c_void_p]
        self.x.XSetErrorHandler.restype = ctypes.c_void_p
        self.x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.display = self.x.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError("Unity volume keys need its X11 display")
        root = self.x.XDefaultRootWindow(self.display)
        self.actions = {}
        self.grab_error = False
        def failed(display, error):
            self.grab_error = True
            return 0
        self.error_handler = self.error_type(failed)
        previous_handler = self.x.XSetErrorHandler(ctypes.cast(self.error_handler, ctypes.c_void_p))
        # CDesktopMediaKeyType: mute=0, up=2, down=4. Quiet variants follow each.
        for name, action in [("XF86AudioMute", 0), ("XF86AudioRaiseVolume", 2), ("XF86AudioLowerVolume", 4)]:
            code = self.x.XKeysymToKeycode(self.display, self.x.XStringToKeysym(name.encode()))
            if code:
                self.actions[code] = action
                for modifiers in [0, 2, 16, 18, 1, 3, 17, 19]:
                    self.x.XGrabKey(self.display, code, modifiers, root, 0, 1, 1)
        self.x.XFlush(self.display)
        self.x.XSync(self.display, 0)
        self.x.XSetErrorHandler(previous_handler)
        if self.grab_error:
            print("volume keys: another X11 client owns one or more bindings", file=sys.stderr, flush=True)
        self.timer = GLib.timeout_add(30, self.poll)

    def poll(self):
        while self.x.XPending(self.display):
            event = self.Event()
            self.x.XNextEvent(self.display, ctypes.byref(event))
            key = ctypes.cast(ctypes.byref(event), ctypes.POINTER(self.KeyEvent)).contents
            if key.type == 2 and key.keycode in self.actions:
                action = self.actions[key.keycode]
                before = self.sink_state()
                # Use the maintained daemon's quiet variant. Unity's player
                # owns the tone and honors its sound preference/theme.
                self.bus.call("org.cinnamon.SettingsDaemon.KeybindingHandler", "/org/cinnamon/SettingsDaemon/KeybindingHandler",
                              "org.cinnamon.SettingsDaemon.KeybindingHandler", "HandleKeybinding",
                              GLib.Variant("(u)", (action + 1,)), None, Gio.DBusCallFlags.NONE, 3000, None,
                              self.replied, (before, bool(key.state & 1)))
        return True

    def sink_state(self):
        try:
            def query(*args):
                return subprocess.run([CONFIG["pactl"], *args], capture_output=True, text=True,
                                      check=True, timeout=2).stdout.strip()
            name = query("get-default-sink")
            sink = next(s for s in json.loads(query("--format=json", "list", "sinks")) if s["name"] == name)
            return sink["mute"], tuple(v["value"] for v in sink["volume"].values())
        except (OSError, subprocess.SubprocessError, StopIteration, ValueError, KeyError):
            return None

    def replied(self, connection, result, feedback):
        try:
            connection.call_finish(result)
            before, quiet = feedback
            if before is not None and not quiet:
                def settled():
                    after = self.sink_state()
                    if after is not None and after != before and not after[0]:
                        self.player.play("audio-volume-change")
                    return False
                GLib.timeout_add(40, settled)
        except GLib.Error as error:
            print("volume key: " + str(error), file=sys.stderr, flush=True)

    def close(self):
        GLib.source_remove(self.timer)
        self.x.XCloseDisplay(self.display)


def sound_settings():
    source = Gio.SettingsSchemaSource.new_from_directory(
        CONFIG["runtime"] + "/usr/share/glib-2.0/schemas", Gio.SettingsSchemaSource.get_default(), False)
    return Gio.Settings.new_full(source.lookup("org.gnome.desktop.sound", False), None, None)


class Player:
    def __init__(self):
        self.settings = sound_settings()
        self.library = ctypes.CDLL(CONFIG["libcanberra"])
        self.context = ctypes.c_void_p()
        self.library.ca_context_create.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self.library.ca_context_set_driver.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self.library.ca_proplist_create.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self.library.ca_proplist_sets.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        self.library.ca_proplist_destroy.argtypes = [ctypes.c_void_p]
        self.callback_type = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p)
        self.library.ca_context_play_full.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                                                    self.callback_type, ctypes.c_void_p]
        self.library.ca_context_destroy.argtypes = [ctypes.c_void_p]
        self.library.ca_strerror.restype = ctypes.c_char_p
        self.pending = {}
        self.serial = 0
        self.check(self.library.ca_context_create(ctypes.byref(self.context)))
        self.check(self.library.ca_context_set_driver(self.context, b"pulse"))

    def check(self, result):
        if result < 0:
            raise RuntimeError(self.library.ca_strerror(result).decode())

    def play(self, event, finished=lambda result: None, filename=None):
        if not self.settings.get_boolean("event-sounds"):
            finished(0)
            return
        if filename is None and self.settings.get_string("theme-name") == "ubuntu":
            for theme, extension in [("ubuntu", "ogg"), ("freedesktop", "oga")]:
                asset = Path(CONFIG["runtime"]) / "usr/share/sounds" / theme / "stereo" / (event + "." + extension)
                if asset.is_file():
                    filename = str(asset)
                    break
        properties = ctypes.c_void_p()
        self.check(self.library.ca_proplist_create(ctypes.byref(properties)))
        self.serial += 1
        serial = self.serial

        def done(context, ident, result, userdata):
            # libcanberra finishes on its audio thread. Keep the callback alive
            # until the main loop has received the completion.
            def complete():
                self.pending.pop(serial, None)
                print("sound %s: %s" % (event, "complete" if result == 0 else
                      self.library.ca_strerror(result).decode()), flush=True)
                finished(result)
                return False
            GLib.idle_add(complete)

        callback = self.callback_type(done)
        self.pending[serial] = callback
        try:
            values = {"event.id": event, "canberra.xdg-theme.name": self.settings.get_string("theme-name"),
                      "application.name": "Unity 12.10", "canberra.cache-control": "never"}
            if filename:
                values.pop("event.id")
                values["media.filename"] = filename
            for key, value in values.items():
                self.check(self.library.ca_proplist_sets(properties, key.encode(), value.encode()))
            result = self.library.ca_context_play_full(self.context, serial, properties, callback, None)
            if result < 0:
                self.pending.pop(serial, None)
                print("sound %s: %s" % (event, self.library.ca_strerror(result).decode()), flush=True)
                finished(result)
        finally:
            self.library.ca_proplist_destroy(properties)

    def close(self):
        self.library.ca_context_destroy(self.context)
        self.pending.clear()


class SessionSounds:
    def __init__(self, bus, player, loop):
        self.bus, self.player, self.loop = bus, player, loop
        self.keys = VolumeKeys(bus, player)
        directory = Path(os.environ["UNITY_QUANTAL_SESSION_DIR"])
        self.marker = directory / "login-sound-played"
        # Registration delays logout until the final sound finishes. Querying
        # logout is not a commitment: cancellation must never play it.
        self.client = self.call(MANAGER_PATH, MANAGER, "RegisterClient",
            GLib.Variant("(ss)", ("unity-quantal-sounds", os.environ.get("DESKTOP_AUTOSTART_ID", "")))).unpack()[0]
        bus.signal_subscribe(MANAGER, MANAGER + ".ClientPrivate", None, self.client, None,
                             Gio.DBusSignalFlags.NONE, self.client_signal)
        bus.signal_subscribe(MANAGER, MANAGER, "SessionRunning", MANAGER_PATH, None,
                             Gio.DBusSignalFlags.NONE, lambda *_: self.login())
        owner = Gio.bus_own_name_on_connection(bus, NAME, Gio.BusNameOwnerFlags.NONE, None, None)
        self.owner = owner
        self.ending = False
        self.logout_timeout = None
        self.trash = Path.home() / ".local/share/Trash/files"
        self.contents = set()
        self.scan_trash(False)
        GLib.timeout_add(500, self.tick)
        if self.call(MANAGER_PATH, MANAGER, "IsSessionRunning", None).unpack()[0]:
            self.login()

    def call(self, path, interface, method, parameters):
        return self.bus.call_sync(MANAGER, path, interface, method, parameters, None,
                                  Gio.DBusCallFlags.NONE, 3000, None)

    def login(self):
        try:
            self.marker.touch(exist_ok=False)
        except FileExistsError:
            return
        self.player.play("desktop-login")

    def response(self):
        try:
            self.call(self.client, MANAGER + ".ClientPrivate", "EndSessionResponse", GLib.Variant("(bs)", (True, "")))
        except GLib.Error:
            self.loop.quit()  # Forced shutdown can close the manager first.
        return False

    def logout_done(self, result):
        if self.logout_timeout is not None:
            GLib.source_remove(self.logout_timeout)
            self.logout_timeout = None
        self.response()

    def logout_expired(self):
        self.logout_timeout = None
        self.response()
        return False

    def client_signal(self, connection, sender, path, interface, name, parameters):
        if name == "QueryEndSession":
            self.response()
        elif name == "EndSession":
            if not self.ending:
                self.ending = True
                # A lost audio server must not hold up shutdown indefinitely.
                self.logout_timeout = GLib.timeout_add_seconds(4, self.logout_expired)
                self.player.play("desktop-logout", self.logout_done)
            else:
                self.response()
        elif name == "CancelEndSession":
            self.ending = False
        elif name == "Stop":
            self.loop.quit()

    def scan_trash(self, play=True):
        try:
            contents = set(self.trash.iterdir()) if self.trash.is_dir() else set()
        except OSError:
            return
        # Emptying/removing trash is the freedesktop trash-empty event; adding
        # files is not. Coalesce a batch into one sound.
        if play and self.contents - contents and not self.ending:
            self.player.play("trash-empty")
        self.contents = contents

    def tick(self):
        self.scan_trash()
        return True


def main():
    # Native libcanberra must see the original themes, even outside FHS.
    os.environ["XDG_DATA_DIRS"] = CONFIG["runtime"] + "/usr/share:" + os.environ.get("XDG_DATA_DIRS", "/usr/share")
    os.environ.setdefault("PULSE_SERVER", "unix:" + os.environ["XDG_RUNTIME_DIR"] + "/pulse/native")
    player = Player()
    loop = GLib.MainLoop()
    try:
        if sys.argv[1:2] == ["play"] and len(sys.argv) == 3:
            result = []
            player.play(sys.argv[2], lambda status: (result.append(status), loop.quit()))
            if not result:
                GLib.timeout_add_seconds(15, loop.quit)
                loop.run()
            return 0 if result == [0] else 1
        if len(sys.argv) != 1:
            raise SystemExit("usage: unity-quantal-sounds [play EVENT]")
        service = SessionSounds(Gio.bus_get_sync(Gio.BusType.SESSION, None), player, loop)
        for sig in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (loop.quit(), False)[1])
        loop.run()
        service.keys.close()
        Gio.bus_unown_name(service.owner)
    finally:
        player.close()


if __name__ == "__main__":
    sys.exit(main())
