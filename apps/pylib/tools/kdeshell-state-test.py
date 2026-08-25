#!/usr/bin/env python3
"""Harness for what the Plasma shell REMEMBERS about its chrome.

    <an app python> apps/pylib/tools/kdeshell-state-test.py

(PySide6 is not in the bare python3 on top: use an app wrapper's interpreter,
e.g. `player-qtenv python3 …`. On book the interpreter is /usr/bin/python3.)

`QMainWindow.saveState()` carries toolbars and docks and NOTHING ELSE, so the
menubar's Ctrl+M answer — and the status bar's — died with the process and he
had to hide the menubar again at every single launch [his, 2026-08-24]. This
drives two shells in a row against one throwaway ini and checks that the second
comes up the way the first was left.

OFFSCREEN, always, and pointed at its own `KDESHELL_STATE` file: it can neither
map a window on his screen nor touch the real `nixdesk` store (~/nix/AGENTS.md
— "Testing without interfering with the user").
"""

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

os.environ["QT_QPA_PLATFORM"] = "offscreen"
STATE = Path(tempfile.mkdtemp(prefix="kdeshell-state-")) / "state.ini"
os.environ["KDESHELL_STATE"] = str(STATE)
os.environ.setdefault("DESK_SESSION", "plasma")

from PySide6.QtWidgets import QApplication  # noqa: E402

import kdeshell  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        fails.append(name)


app = QApplication(sys.argv)
app.setApplicationName("kdeshell-state-test")

print("what the shell remembers")

# ---- a store with nothing in it leaves the app's own defaults alone ------
first = kdeshell.shell("state-test", size=(600, 400), min_size=(200, 200))
first._ensure_status()
first.show()
check("with an empty store the menubar comes up as the app left it",
      not first.window.menuBar().isHidden())
check("...and so does the status bar", not first._bar_widget("statusbar").isHidden())

# ---- hide them, quit ----------------------------------------------------
# Through the Settings rows, the way he does it — the actions take their
# checked state FROM the widgets, so they have to be synced before a click on
# one means anything.
first._toggle_action("menubar")
first._toggle_action("statusbar")
first._sync_toggles()
first._toggle_action("menubar").setChecked(False)
first._toggle_action("statusbar").setChecked(False)
check("the toggle actually hid the menubar", first.window.menuBar().isHidden())
first._save_state()
check("the ini was written", STATE.exists(), str(STATE))

# ---- a second launch reads it back --------------------------------------
second = kdeshell.shell("state-test", size=(600, 400), min_size=(200, 200))
second._ensure_status()
second.show()
check("the menubar comes back hidden", second.window.menuBar().isHidden())
check("...and the status bar with it", second._bar_widget("statusbar").isHidden())
check("Show Menubar says so, so Ctrl+M puts it back",
      not second._toggle_action("menubar").isChecked())

# ---- and back on ---------------------------------------------------------
second._toggle_action("menubar").setChecked(True)
second._save_state()
third = kdeshell.shell("state-test", size=(600, 400), min_size=(200, 200))
third.show()
check("showing it again is remembered too", not third.window.menuBar().isHidden())

print("FAILED: " + ", ".join(fails) if fails else "all ok")
sys.exit(1 if fails else 0)
