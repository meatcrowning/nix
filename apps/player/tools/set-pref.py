#!/usr/bin/env python3
"""Set one key in the player's prefs.json — safely, from outside the app.

    tools/set-pref.py tagWrites on
    tools/set-pref.py lyricsEmbed --json false
    tools/set-pref.py --show

**It refuses to run while main.py is up**, the same rule tools/lyrics-sync.py
follows for --write, and for a sharper reason here: Prefs keeps the whole file
in memory and rewrites ALL of it on every set() — a volume nudge, a sort change,
an album-grid scroll, or quitting (which saves the queue). A key added to the
file underneath a running player is therefore both invisible to it (prefs are
read once, at startup) and erased by its next write. Editing live is not a race
you can win; quit the player, run this, relaunch.

A timestamped backup of the previous file is written beside it.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "player"
PREFS = STATE / "prefs.json"
APP = str(Path(__file__).resolve().parent.parent / "main.py")


def player_running():
    try:
        out = subprocess.run(["pgrep", "-af", "player/main.py"],
                             capture_output=True, text=True).stdout
    except OSError:
        return False
    return any(APP in line for line in out.splitlines())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("key", nargs="?")
    ap.add_argument("value", nargs="?")
    ap.add_argument("--json", action="store_true",
                    help="parse VALUE as JSON (numbers, true/false, null)")
    ap.add_argument("--show", action="store_true", help="print prefs and exit")
    a = ap.parse_args()

    d = {}
    if PREFS.exists():
        d = json.loads(PREFS.read_text(encoding="utf-8"))
    if a.show or not a.key:
        for k, v in sorted(d.items()):
            print("%-14s %s" % (k, json.dumps(v)[:100]))
        return 0
    if a.value is None:
        sys.exit("need a value (or --show)")
    if player_running():
        sys.exit("player is running — quit it first, or its next prefs write "
                 "will erase this key (see the module docstring)")

    val = json.loads(a.value) if a.json else a.value
    old = d.get(a.key, "<unset>")
    shutil.copy2(PREFS, PREFS.with_suffix(".json.bak-%s" % time.strftime("%Y%m%d-%H%M%S"))) \
        if PREFS.exists() else None
    d[a.key] = val
    tmp = PREFS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    os.replace(tmp, PREFS)
    print("%s: %s -> %s" % (a.key, json.dumps(old), json.dumps(val)))
    print("relaunch player for it to take effect")
    return 0


if __name__ == "__main__":
    sys.exit(main())
