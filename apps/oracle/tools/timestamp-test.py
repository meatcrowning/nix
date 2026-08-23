#!/usr/bin/env python3
"""A turn knows WHEN it happened, and an old one says so to the model.

The system prompt carries "the current time right now", built at send time,
while the transcript under it carried no times at all — so a session reopened
days later read as if all of it had just been said. This drives the real window
(offscreen, no daemon touched, nothing on his screen) with a demo transcript
spanning two days and reads back the three things that changed:

    times ts:       the stamp survived the store round-trip
    times stamped:  an old prompt of HIS goes into history with its time on it,
                    and the model's own replies never do (nothing to imitate)
    times newday:   only the first turn of a new day draws a date above it
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
fails = []


def check(label, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + label + (("  " + detail) if detail else ""))
    if not ok:
        fails.append(label)


env = dict(os.environ, ORACLE_FAKE="1", ORACLE_TIMES="1",
           QT_QPA_PLATFORM="offscreen")
env.pop("WAYLAND_DISPLAY", None)
env.pop("DISPLAY", None)
out = subprocess.run([sys.executable, str(APP / "main.py"), "--selftest"],
                     env=env, capture_output=True, text=True, timeout=240)
txt = out.stdout + out.stderr


def line(name):
    m = re.search(r"^times %s: (.*)$" % name, txt, re.M)
    return json.loads(m.group(1)) if m else None


ts, stamped, newday = line("ts"), line("stamped"), line("newday")
if ts is None or stamped is None or newday is None:
    print(txt[-1500:])
    print("FAILED: the harness printed no times")
    sys.exit(1)

check("the window still loads clean", "0 QML warning(s)" in txt)
check("every row came back with its stamp", all(isinstance(t, int) and t > 0
                                                for t in ts), json.dumps(ts))
check("the stamps are in order", ts == sorted(ts))
check("an old prompt of his carries its time into history",
      stamped[0].startswith("[sent ") and " local] hi" in stamped[0],
      stamped[0])
check("the model's own turns are never stamped",
      not any(s.startswith("[sent ") for i, s in enumerate(stamped) if i % 2))
check("a new day draws a date, once", newday.count(True) == 1,
      json.dumps(newday))
check("and it is the first turn of that day", newday.index(True) == 4
      if True in newday else False)

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
