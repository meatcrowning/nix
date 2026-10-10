"""Mirror settings Unity's tools write onto the keys their readers use.

GNOME Tweak Tool 3.6 writes the GNOME 3.6 keys. In this session the power
daemon is Cinnamon's, which reads org.cinnamon.* from the user's normal dconf
profile; Unity's clock reads indicator-datetime's own keys; and Ubuntu's 12.10
keyboard plugin reads libgnomekbd's options, not input-sources (so the tool's
Typing tab did nothing on 12.10 itself). Each pair is mirrored both ways; at
start the reader's current value wins. The pairs and the rest of the tool's
keys are listed in tweaks.json.
"""

import ast
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

from gi.repository import Gio, GLib

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text())
RUNTIME = str(HERE.parent.parent / "bin/unity-quantal-runtime")
NAME = "org.unity_quantal.SettingsMirror"


def strings(text):
    return [] if text.endswith("[]") else ast.literal_eval(text)


def string_array(items):
    return "[" + ", ".join(repr(item) for item in items) + "]" if items else "@as []"


def to_gnomekbd(text):
    """xkb-options' "caps:none" is libgnomekbd's "caps<TAB>caps:none"."""
    return string_array([option.split(":")[0] + "\t" + option for option in strings(text)])


def from_gnomekbd(text):
    return string_array([option.split("\t")[-1] for option in strings(text)])


# (tool side, reader side, tool-to-reader, reader-to-tool); a side is
# (profile, schema, key).
PAIRS = [
    (("unity", "org.gnome.settings-daemon.plugins.power", key),
     ("native", "org.cinnamon.settings-daemon.plugins.power", key), None, None)
    for key in ["button-power", "lid-close-ac-action", "lid-close-battery-action"]
] + [
    (("unity", "org.gnome.desktop.interface", "clock-show-" + key),
     ("unity", "com.canonical.indicator.datetime", "show-" + key), None, None)
    for key in ["date", "seconds"]
] + [
    (("unity", "org.gnome.desktop.input-sources", "xkb-options"),
     ("unity", "org.gnome.libgnomekbd.keyboard", "options"), to_gnomekbd, from_gnomekbd),
]
NATIVE = dict(os.environ, XDG_DATA_DIRS=":".join(
    [CONFIG["settingsData"], os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")]))


def die_with_parent():
    # PR_SET_PDEATHSIG: a killed mirror leaves no monitors behind.
    ctypes.CDLL(None).prctl(1, signal.SIGTERM)


def gsettings(side, *arguments):
    if side[0] == "unity":
        return [RUNTIME, "/usr/bin/gsettings", *arguments], None
    return [CONFIG["gsettings"], *arguments], NATIVE


def read(side):
    command, environment = gsettings(side, "get", side[1], side[2])
    return subprocess.run(command, env=environment, capture_output=True, text=True, check=True).stdout.strip()


def write(side, value):
    command, environment = gsettings(side, "set", side[1], side[2], value)
    subprocess.run(command, env=environment, check=True)


class Pair:
    """Each side's last value, so the echo of a mirrored write is ignored."""

    def __init__(self, tool, reader, to_reader, to_tool):
        self.sides = (tool, reader)
        self.convert = {tool: to_reader or str, reader: to_tool or str}
        self.lock = threading.Lock()
        self.values = {reader: read(reader), tool: read(tool)}
        wanted = self.convert[reader](self.values[reader])
        if self.values[tool] != wanted:
            self.values[tool] = wanted
            write(tool, wanted)

    def changed(self, side, value):
        with self.lock:
            if value == self.values[side]:
                return
            other = self.sides[1] if side == self.sides[0] else self.sides[0]
            self.values[side] = value
            self.values[other] = self.convert[side](value)
            print(f"mirror: {side[1]} {side[2]} = {value} -> {other[1]} {other[2]}", file=sys.stderr)
            write(other, self.values[other])


def follow(pair, side, loop):
    command, environment = gsettings(side, "monitor", side[1], side[2])
    process = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE, text=True,
                               preexec_fn=die_with_parent)
    for line in process.stdout:
        key, _, value = line.partition(": ")
        if key.strip() == side[2]:
            pair.changed(side, value.strip())
    # A monitor that ends leaves the pair unmirrored; the session restarts us.
    print(f"mirror: monitor for {side[1]} {side[2]} ended", file=sys.stderr)
    GLib.idle_add(loop.quit)


def main():
    loop = GLib.MainLoop()
    Gio.bus_own_name(Gio.BusType.SESSION, NAME, Gio.BusNameOwnerFlags.NONE,
                     None, None, lambda *_: loop.quit())
    for tool, reader, to_reader, to_tool in PAIRS:
        pair = Pair(tool, reader, to_reader, to_tool)
        for side in (tool, reader):
            threading.Thread(target=follow, args=(pair, side, loop), daemon=True).start()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, loop.quit)
    loop.run()
    # Every exit is unexpected or a refresh; either way the session restarts it.
    return 1


if __name__ == "__main__":
    sys.exit(main())
