"""Check GNOME Tweak Tool's keys against their readers in the Unity session.

Run by tools/unity-quantal-test.sh inside its headless session:
  unity-tweaks-check.py PACKAGE MAP INVENTORY
The inventory (tools/unity-tweaks-inventory.py) must list exactly the keys and
hidden schemas in the map (lib/unity-quantal/tweaks.json). Each key with an
automatic check is set to a probe value and must reach its reader: the
XSETTINGS the settings daemon publishes, the keyboard map, or the mirrored key.
Keys checked by name in the harness or by hand are listed, not run.
"""

import json
import os
import subprocess
import sys
import time

package, map_path, inventory_path = sys.argv[1:]
config = json.load(open(os.path.join(package, "libexec/unity-quantal/config.json")))
runtime = os.path.join(package, "bin/unity-quantal-runtime")
tweaks = json.load(open(map_path))
inventory = json.load(open(inventory_path))
native = dict(os.environ, XDG_DATA_DIRS=config["settingsData"] + ":" + os.environ.get("XDG_DATA_DIRS", ""))
failures = []


def fail(message):
    print("FAIL: " + message)
    failures.append(message)


def gsettings(profile, *arguments):
    command = [runtime, "/usr/bin/gsettings"] if profile == "unity" else [config["gsettings"]]
    result = subprocess.run(command + list(arguments), env=None if profile == "unity" else native,
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(" ".join(arguments) + ": " + result.stderr.strip())
    return result.stdout.strip()


def xsetting(name):
    return subprocess.run([runtime, "/usr/bin/python2.7", "-c",
                           "from gi.repository import Gtk\n"
                           "print(Gtk.Settings.get_default().get_property(%r))" % name],
                          capture_output=True, text=True).stdout.strip()


def xkb_options():
    query = subprocess.run(["setxkbmap", "-query"], capture_output=True, text=True).stdout
    return next((line.split(":", 1)[1].strip() for line in query.splitlines() if line.startswith("options:")), "")


def until(read, expected, seconds=8):
    value = None
    deadline = time.time() + seconds
    while time.time() < deadline:
        value = read()
        if expected(value):
            return True, value
        time.sleep(0.25)
    return False, value


for kind, mapped, found in [("key", set(tweaks["keys"]), set(inventory["keys"])),
                            ("hidden schema", set(tweaks["hidden"]), set(inventory["missing"]))]:
    for name in sorted(found - mapped):
        fail(f"Tweak Tool shows {kind} {name}, which tweaks.json does not map")
    for name in sorted(mapped - found):
        fail(f"tweaks.json maps {kind} {name}, which Tweak Tool no longer shows")

for name, entry in sorted(tweaks["keys"].items()):
    check = entry["check"]
    if "set" not in check:
        print("LISTED: " + name + " -> " + entry["reader"] + " (" + next(iter(check)) + ")")
        continue
    schema, key = name.split()
    try:
        gsettings("unity", "set", schema, key, check["set"])
        if "xsettings" in check:
            ok, value = until(lambda: xsetting(check["xsettings"]), lambda v: v == check["expect"])
            seen = check["xsettings"] + "=" + str(value)
        elif "xkb" in check:
            ok, value = until(xkb_options, lambda v: check["xkb"] in v.split(","))
            seen = "xkb options=" + value
        else:
            profile, reader_schema, reader_key = check["mirror"]
            ok, value = until(lambda: gsettings(profile, "get", reader_schema, reader_key),
                              lambda v: v == check["set"])
            seen = reader_schema + " " + reader_key + "=" + value
            if ok:
                # And back: the reader's own settings reach the tool.
                gsettings(profile, "reset", reader_schema, reader_key)
                default = gsettings(profile, "get", reader_schema, reader_key)
                ok, value = until(lambda: gsettings("unity", "get", schema, key), lambda v: v == default)
                seen += "; reset reader -> tool " + value
        gsettings("unity", "reset", schema, key)
    except RuntimeError as error:
        ok, seen = False, str(error)
    if ok:
        print("PASS: " + name + " -> " + seen)
    else:
        fail(name + " did not reach " + entry["reader"] + " (" + seen + ")")

if failures:
    sys.exit(f"{len(failures)} Tweak Tool settings are not wired")
print("PASS: every Tweak Tool key is mapped, and every automatic check reached its reader")
