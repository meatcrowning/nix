#!/usr/bin/python2.7
"""CPU frequency indicator for the Unity session.

indicator-cpufreq's panel meter, over current hardware: amd-pstate offers no
fixed frequencies or userspace governor to pick, so the menu switches
power-profiles-daemon's profiles instead (active local sessions need no
password). Runs on the original runtime's Python 2.7, GTK 3.6 and AppIndicator.
"""
from __future__ import division, print_function

import glob
import os
import sys

from gi.repository import Gio, GLib, GObject, Gtk

# The original indicator-cpufreq meter icons, passed by the session command.
ICONS = sys.argv[1] if len(sys.argv) > 1 else ""
PROFILES = [("performance", "Performance"), ("balanced", "Balanced"), ("power-saver", "Power Saver")]
INTERVAL = 2


def read_khz(path):
    try:
        with open(path) as stream:
            return int(stream.read())
    except (IOError, OSError, ValueError):
        return 0


def sample():
    """Average and peak current frequency, and the hardware maximum, in kHz."""
    current = [value for value in (read_khz(path) for path in
               glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")) if value]
    maximum = max([read_khz(path) for path in
                   glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/cpuinfo_max_freq")] or [0])
    if not current:
        return 0, 0, maximum
    return sum(current) // len(current), max(current), maximum


def ghz(khz):
    return "%.2f GHz" % (khz / 1e6)


class Indicator(Gtk.Application):
    def __init__(self):
        Gtk.Application.__init__(self, application_id="org.unity_quantal.CpuFreq",
                                 flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.started = False

    def do_activate(self):
        if self.started:
            return
        self.started = True
        from gi.repository import AppIndicator3
        self.hold()
        self.indicator = AppIndicator3.Indicator.new_with_path(
            "unity-quantal-cpufreq", "indicator-cpufreq",
            AppIndicator3.IndicatorCategory.HARDWARE, ICONS)
        self.indicator.set_title("CPU Frequency")
        menu = Gtk.Menu()
        self.average = Gtk.MenuItem("")
        self.peak = Gtk.MenuItem("")
        for item in (self.average, self.peak):
            item.set_sensitive(False)
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        self.profiles = []
        for name, label in PROFILES:
            item = Gtk.CheckMenuItem(label)
            item.set_draw_as_radio(True)
            item.connect("activate", self.choose, name)
            menu.append(item)
            self.profiles.append((name, item))
        self.degraded = Gtk.MenuItem("")
        self.degraded.set_sensitive(False)
        menu.append(self.degraded)
        menu.show_all()
        self.updating = False
        self.indicator.set_menu(menu)
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        self.daemon = None
        try:
            self.daemon = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None, "net.hadess.PowerProfiles",
                "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles", None)
            self.daemon.connect("g-properties-changed", lambda *_: self.show_profile())
            # Picks up a daemon that starts or restarts after this indicator.
            self.daemon.connect("notify::g-name-owner", lambda *_: self.show_profile())
        except GLib.GError as error:
            print("cpufreq: no power profiles: " + str(error), file=sys.stderr)
        self.show_profile()
        self.tick()
        GLib.timeout_add_seconds(INTERVAL, self.tick)

    def tick(self):
        average, peak, maximum = sample()
        self.average.set_label("Average: " + (ghz(average) if average else "unknown"))
        self.peak.set_label("Fastest core: " + (ghz(peak) if peak else "unknown"))
        if average and maximum:
            level = min(100, max(25, -(-average * 4 // maximum) * 25))
            self.indicator.set_icon("indicator-cpufreq-%d" % level)
        else:
            self.indicator.set_icon("indicator-cpufreq")
        return True

    def property(self, name):
        value = self.daemon.get_cached_property(name) if self.daemon else None
        return value.unpack() if value is not None else None

    def show_profile(self):
        active = self.property("ActiveProfile")
        offered = set(profile.get("Profile") for profile in (self.property("Profiles") or []))
        self.updating = True
        for name, item in self.profiles:
            item.set_active(name == active)
            item.set_sensitive(name in offered)
        self.updating = False
        reason = self.property("PerformanceDegraded")
        self.degraded.set_label("Performance limited: " + reason if reason else
                                "" if offered else "Power profiles unavailable")
        self.degraded.set_visible(bool(reason) or not offered)

    def choose(self, item, name):
        if self.updating:
            return
        if item.get_active() and self.daemon:
            try:
                self.daemon.call_sync(
                    "org.freedesktop.DBus.Properties.Set",
                    GLib.Variant("(ssv)", ("net.hadess.PowerProfiles", "ActiveProfile", GLib.Variant("s", name))),
                    Gio.DBusCallFlags.NONE, 5000, None)
            except GLib.GError as error:
                print("cpufreq: cannot select " + name + ": " + str(error), file=sys.stderr)
        # The daemon's PropertiesChanged settles the radio; undo a refused pick.
        self.show_profile()


if __name__ == "__main__":
    GLib.set_prgname("unity-cpufreq")
    GObject.threads_init()
    sys.exit(Indicator().run(sys.argv[:1]))
