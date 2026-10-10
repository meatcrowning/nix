#!/usr/bin/python2.7
"""Software brightness and night light for the Unity session.

Top's display has no backlight and may lack DDC/CI (its projector does), so
both controls shape one XRandR gamma ramp. This runs on the original runtime's
Python 2.7, GTK 3.6 and AppIndicator: `indicator` is the session component
(brightness keys, notify-osd bubble, panel menu); `settings` is the panel
opened from System Settings. They share one state file and both apply it.
"""
from __future__ import division, print_function

import ctypes
import json
import math
import os
import signal
import subprocess
import sys

from gi.repository import Gdk, Gio, GLib, GObject, Gtk

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                     "unity-quantal", "display.json")
DEFAULTS = {"brightness": 100, "night": False, "temperature": 4000}
MIN_BRIGHTNESS, STEP = 10, 5
COOLEST, WARMEST = 6000, 3000


def load():
    state = dict(DEFAULTS)
    try:
        with open(STATE) as stream:
            data = json.load(stream)
        state["brightness"] = int(data.get("brightness", state["brightness"]))
        state["night"] = bool(data.get("night", state["night"]))
        state["temperature"] = int(data.get("temperature", state["temperature"]))
    except (IOError, OSError, ValueError, TypeError, AttributeError):
        pass
    state["brightness"] = max(MIN_BRIGHTNESS, min(100, state["brightness"]))
    state["temperature"] = max(WARMEST, min(COOLEST, state["temperature"]))
    return state


def save(state):
    directory = os.path.dirname(STATE)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    temporary = STATE + ".tmp"
    with open(temporary, "w") as stream:
        json.dump(state, stream, sort_keys=True)
    os.rename(temporary, STATE)


def whitepoint(kelvin):
    """Approximate black-body white point (Tanner Helland's fit), 0..1 per channel."""
    t = kelvin / 100.0
    red = 1.0 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592 / 255
    if t <= 66:
        green = (99.4708025861 * math.log(t) - 161.1195681661) / 255
    else:
        green = 288.1221695283 * (t - 60) ** -0.0755148492 / 255
    if t >= 66:
        blue = 1.0
    elif t <= 19:
        blue = 0.0
    else:
        blue = (138.5177312231 * math.log(t - 10) - 305.0447927307) / 255
    channels = [max(0.0, min(1.0, value)) for value in (red, green, blue)]
    peak = max(channels)
    return [value / peak for value in channels]


class XRRScreenResources(ctypes.Structure):
    _fields_ = [("timestamp", ctypes.c_ulong), ("configTimestamp", ctypes.c_ulong),
                ("ncrtc", ctypes.c_int), ("crtcs", ctypes.POINTER(ctypes.c_ulong)),
                ("noutput", ctypes.c_int), ("outputs", ctypes.POINTER(ctypes.c_ulong)),
                ("nmode", ctypes.c_int), ("modes", ctypes.c_void_p)]


class XRRCrtcGamma(ctypes.Structure):
    _fields_ = [("size", ctypes.c_int), ("red", ctypes.POINTER(ctypes.c_ushort)),
                ("green", ctypes.POINTER(ctypes.c_ushort)), ("blue", ctypes.POINTER(ctypes.c_ushort))]


class XKeyEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("root", ctypes.c_ulong),
                ("subwindow", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("x", ctypes.c_int), ("y", ctypes.c_int), ("x_root", ctypes.c_int), ("y_root", ctypes.c_int),
                ("state", ctypes.c_uint), ("keycode", ctypes.c_uint), ("same_screen", ctypes.c_int)]


class XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("xkey", XKeyEvent), ("pad", ctypes.c_long * 24)]


ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


class Screen(object):
    """A private X connection for the gamma ramp and the brightness-key grabs."""

    def __init__(self):
        x11 = self.x11 = ctypes.CDLL("libX11.so.6")
        xrr = self.xrr = ctypes.CDLL("libXrandr.so.2")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XConnectionNumber.argtypes = [ctypes.c_void_p]
        x11.XPending.argtypes = [ctypes.c_void_p]
        x11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(XEvent)]
        x11.XFlush.argtypes = [ctypes.c_void_p]
        x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x11.XStringToKeysym.restype = ctypes.c_ulong
        x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x11.XKeysymToKeycode.restype = ctypes.c_ubyte
        x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XGrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_int]
        x11.XSetErrorHandler.restype = ctypes.c_void_p
        x11.XSetErrorHandler.argtypes = [ctypes.c_void_p]
        xrr.XRRGetScreenResourcesCurrent.restype = ctypes.POINTER(XRRScreenResources)
        xrr.XRRGetScreenResourcesCurrent.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xrr.XRRFreeScreenResources.argtypes = [ctypes.POINTER(XRRScreenResources)]
        xrr.XRRGetCrtcGammaSize.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xrr.XRRAllocGamma.restype = ctypes.POINTER(XRRCrtcGamma)
        xrr.XRRAllocGamma.argtypes = [ctypes.c_int]
        xrr.XRRSetCrtcGamma.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XRRCrtcGamma)]
        xrr.XRRFreeGamma.argtypes = [ctypes.POINTER(XRRCrtcGamma)]
        self.display = x11.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError("Cannot open the X display")
        self.root = x11.XDefaultRootWindow(self.display)
        self.keys = {}

    def apply(self, state):
        scale = state["brightness"] / 100.0
        white = whitepoint(state["temperature"]) if state["night"] else [1.0, 1.0, 1.0]
        resources = self.xrr.XRRGetScreenResourcesCurrent(self.display, self.root)
        if not resources:
            return
        try:
            for index in range(resources.contents.ncrtc):
                crtc = resources.contents.crtcs[index]
                size = self.xrr.XRRGetCrtcGammaSize(self.display, crtc)
                if size < 2:
                    continue
                gamma = self.xrr.XRRAllocGamma(size)
                for channel, factor in zip((gamma.contents.red, gamma.contents.green, gamma.contents.blue), white):
                    for step in range(size):
                        channel[step] = int(round(65535.0 * step / (size - 1) * scale * factor))
                self.xrr.XRRSetCrtcGamma(self.display, crtc, gamma)
                self.xrr.XRRFreeGamma(gamma)
        finally:
            self.xrr.XRRFreeScreenResources(resources)
        self.x11.XFlush(self.display)

    def grab(self, keys):
        """Grab keysym -> step; nothing else in this session listens for these keys."""
        failed = []
        handler = ERROR_HANDLER(lambda display, event: failed.append(True) or 0)
        previous = self.x11.XSetErrorHandler(ctypes.cast(handler, ctypes.c_void_p))
        try:
            for name, step in keys.items():
                code = self.x11.XKeysymToKeycode(self.display, self.x11.XStringToKeysym(name.encode("ascii")))
                if not code:
                    continue
                # Unity holds Alt+any and Super+any, so AnyModifier is refused.
                # Take every Shift/Lock/Control/NumLock combination instead
                # (owner_events, GrabModeAsync for pointer and keyboard).
                for modifiers in range(16):
                    mask = sum(bit for index, bit in enumerate((1, 2, 4, 16)) if modifiers >> index & 1)
                    self.x11.XGrabKey(self.display, code, mask, self.root, 1, 1, 1)
                self.keys[code] = step
            self.x11.XSync(self.display, 0)
        finally:
            self.x11.XSetErrorHandler(previous)
        if failed:
            print("display: another client holds the brightness keys", file=sys.stderr)

    def watch(self, callback):
        event = XEvent()

        def ready(*_arguments):
            while self.x11.XPending(self.display):
                self.x11.XNextEvent(self.display, ctypes.byref(event))
                if event.type == 2 and event.xkey.keycode in self.keys:  # KeyPress
                    callback(self.keys[event.xkey.keycode])
            return True
        # pygobject 3.4 keeps fd watches on GObject.
        GObject.io_add_watch(self.x11.XConnectionNumber(self.display), GObject.IO_IN, ready)


def osd(value):
    """notify-osd's synchronous brightness bubble, as Ubuntu 12.10 showed it."""
    level = ("off" if value <= 0 else "low" if value < 33 else "medium" if value < 66
             else "high" if value < 100 else "full")
    hints = {"x-canonical-private-synchronous": GLib.Variant("s", "brightness"),
             "value": GLib.Variant("i", value)}
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                      "org.freedesktop.Notifications", "Notify",
                      GLib.Variant("(susssasa{sv}i)", ("Brightness", 0, "display-brightness-" + level,
                                                      " ", "", [], hints, -1)),
                      None, Gio.DBusCallFlags.NONE, 2000, None)
    except GLib.GError as error:
        print("display: no brightness bubble: " + str(error), file=sys.stderr)


def watch_state(callback):
    """Follow writes from the other face; renames arrive as created/moved events."""
    directory = os.path.dirname(STATE)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    monitor = Gio.File.new_for_path(directory).monitor_directory(Gio.FileMonitorFlags.NONE, None)

    def changed(_monitor, file, _other, event):
        if file.get_path() == STATE and event != Gio.FileMonitorEvent.DELETED:
            callback()
    monitor.connect("changed", changed)
    return monitor


class Indicator(Gtk.Application):
    LEVELS = [100, 75, 50, 25]

    def __init__(self):
        Gtk.Application.__init__(self, application_id="org.unity_quantal.Display",
                                 flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.started = False

    def do_activate(self):
        if self.started:
            return
        self.started = True
        from gi.repository import AppIndicator3
        self.hold()
        self.state = load()
        self.screen = Screen()
        self.screen.apply(self.state)
        self.screen.grab({"XF86MonBrightnessUp": STEP, "XF86MonBrightnessDown": -STEP})
        self.screen.watch(self.step)
        # A mode change or hotplug resets the CRTC ramps.
        Gdk.Screen.get_default().connect("monitors-changed", lambda *_: self.screen.apply(self.state))
        self.monitor = watch_state(self.reload)

        self.indicator = AppIndicator3.Indicator.new_with_path(
            "unity-quantal-display", "unity-display-day",
            AppIndicator3.IndicatorCategory.HARDWARE, os.path.join(HERE, "display-icons"))
        self.indicator.set_title("Display")
        self.indicator.connect("scroll-event", self.scroll)
        menu = Gtk.Menu()
        self.heading = Gtk.MenuItem("")
        self.heading.set_sensitive(False)
        menu.append(self.heading)
        self.levels = []
        for level in self.LEVELS:
            item = Gtk.CheckMenuItem(str(level) + "%")
            item.set_draw_as_radio(True)
            item.connect("activate", self.choose, level)
            menu.append(item)
            self.levels.append((level, item))
        menu.append(Gtk.SeparatorMenuItem())
        self.night = Gtk.CheckMenuItem("Night Light")
        self.night.connect("toggled", self.toggle_night)
        menu.append(self.night)
        menu.append(Gtk.SeparatorMenuItem())
        settings = Gtk.MenuItem(u"Display Settings\u2026")
        settings.connect("activate", lambda *_: subprocess.Popen([sys.executable, os.path.abspath(__file__), "settings"]))
        menu.append(settings)
        menu.show_all()
        self.menu_updating = False
        self.indicator.set_menu(menu)
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.show()

    def show(self):
        self.menu_updating = True
        self.heading.set_label("Brightness: " + str(self.state["brightness"]) + "%")
        for level, item in self.levels:
            item.set_active(level == self.state["brightness"])
        self.night.set_active(self.state["night"])
        self.menu_updating = False
        self.indicator.set_icon("unity-display-night" if self.state["night"] else "unity-display-day")

    def change(self, **values):
        self.state.update(values)
        self.state["brightness"] = max(MIN_BRIGHTNESS, min(100, self.state["brightness"]))
        self.screen.apply(self.state)
        save(self.state)
        self.show()

    def reload(self):
        state = load()
        if state != self.state:
            self.state = state
            self.screen.apply(state)
            self.show()

    def step(self, delta):
        self.change(brightness=self.state["brightness"] + delta)
        osd(self.state["brightness"])

    def scroll(self, _indicator, _steps, direction):
        if direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.DOWN):
            self.step(STEP if direction == Gdk.ScrollDirection.UP else -STEP)

    def choose(self, item, level):
        if not self.menu_updating and item.get_active():
            self.change(brightness=level)
        elif not self.menu_updating:
            self.show()

    def toggle_night(self, item):
        if not self.menu_updating:
            self.change(night=item.get_active())


class Settings(Gtk.Application):
    def __init__(self):
        Gtk.Application.__init__(self, application_id="org.unity_quantal.DisplaySettings",
                                 flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None

    def do_activate(self):
        if self.window:
            self.window.present()
            return
        self.state = load()
        self.screen = Screen()
        self.updating = False
        window = self.window = Gtk.ApplicationWindow(application=self, title="Brightness & Night Light")
        window.set_icon_name("preferences-desktop-display")
        window.set_resizable(False)
        window.set_border_width(12)

        grid = Gtk.Grid(row_spacing=12, column_spacing=12)
        window.add(grid)

        def label(text, row):
            widget = Gtk.Label(text)
            widget.set_alignment(1.0, 0.5)
            grid.attach(widget, 0, row, 1, 1)

        label("Brightness", 0)
        self.brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, MIN_BRIGHTNESS, 100, STEP)
        self.brightness.set_draw_value(False)
        self.brightness.set_size_request(380, -1)
        self.brightness.connect("value-changed", self.changed)
        grid.attach(self.brightness, 1, 0, 1, 1)

        label("Night Light", 1)
        self.night = Gtk.Switch()
        self.night.set_halign(Gtk.Align.START)
        self.night.connect("notify::active", self.changed)
        grid.attach(self.night, 1, 1, 1, 1)

        label("Warmth", 2)
        # Ubuntu's panels flank a scale with its two ends, like Mouse's Slow/Fast.
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.cooler = Gtk.Label("Cooler")
        self.warmer = Gtk.Label("Warmer")
        # Inverted: kelvin falls as the slider moves toward Warmer.
        self.temperature = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, WARMEST, COOLEST, 100)
        self.temperature.set_inverted(True)
        self.temperature.set_draw_value(False)
        self.temperature.connect("value-changed", self.changed)
        row.pack_start(self.cooler, False, False, 0)
        row.pack_start(self.temperature, True, True, 0)
        row.pack_start(self.warmer, False, False, 0)
        grid.attach(row, 1, 2, 1, 1)

        self.show()
        self.monitor = watch_state(self.reload)
        window.show_all()

    def show(self):
        self.updating = True
        self.brightness.set_value(self.state["brightness"])
        self.night.set_active(self.state["night"])
        self.temperature.set_value(self.state["temperature"])
        for widget in (self.temperature, self.cooler, self.warmer):
            widget.set_sensitive(self.state["night"])
        self.updating = False

    def changed(self, *_arguments):
        if self.updating:
            return
        self.state = {"brightness": int(round(self.brightness.get_value())),
                      "night": self.night.get_active(),
                      "temperature": int(round(self.temperature.get_value()))}
        for widget in (self.temperature, self.cooler, self.warmer):
            widget.set_sensitive(self.state["night"])
        # Apply here too, so dragging does not wait for the indicator to notice.
        self.screen.apply(self.state)
        save(self.state)

    def reload(self):
        state = load()
        if state != self.state:
            self.state = state
            self.show()


if __name__ == "__main__":
    # The window class matches unity-display.desktop, so the launcher shows its icon.
    GLib.set_prgname("unity-display")
    # Children (the settings panel) are reaped by the kernel.
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    application = {"indicator": Indicator, "settings": Settings}.get(sys.argv[1] if len(sys.argv) > 1 else "")
    if application is None:
        raise SystemExit("usage: display.py indicator|settings")
    sys.exit(application().run(sys.argv[:1]))
