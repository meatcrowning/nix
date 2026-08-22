#!/usr/bin/env python3
"""Offscreen checks for winstate.py — save/restore round-trip and the guards.

Never touches a real screen: forces the offscreen platform (hard, per
apps/AGENTS.md) and points XDG_STATE_HOME at a throwaway dir.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)
_tmp = tempfile.mkdtemp(prefix="winstate-test-")
os.environ["XDG_STATE_HOME"] = _tmp
os.environ["XDG_CONFIG_HOME"] = _tmp
# The KWin-rule path is off unless we look like a Plasma session.
os.environ.pop("KDE_FULL_SESSION", None)
os.environ.pop("XDG_CURRENT_DESKTOP", None)
os.environ.pop("XDG_SESSION_DESKTOP", None)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # apps/pylib

from PySide6.QtGui import QGuiApplication, QWindow          # noqa: E402
from winstate import (WinState, _state_path,                # noqa: E402
                      _kwinrules_path, _parse_kconfig)

app = QGuiApplication(sys.argv)
if app.platformName() != "offscreen":
    raise SystemExit("refusing to run on platform %r, not offscreen" % app.platformName())

fails = []


def check(name, cond):
    print(("ok  " if cond else "FAIL") + "  " + name)
    if not cond:
        fails.append(name)


def make_win(x=100, y=120, w=640, h=480):
    win = QWindow()
    win.setGeometry(x, y, w, h)
    return win


# 1. round-trip: a saved geometry is restored onto a fresh window.
w1 = make_win(200, 150, 800, 600)
ws1 = WinState(w1, "app-rt")
ws1._save()
p = _state_path("app-rt")
check("state file written", p.exists())

w2 = make_win(0, 0, 300, 300)
WinState(w2, "app-rt")
check("width restored", w2.width() == 800)
check("height restored", w2.height() == 600)

# 2. zero / garbage size is dropped, window keeps its own size.
_state_path("app-zero").parent.mkdir(parents=True, exist_ok=True)
_state_path("app-zero").write_text('{"x":10,"y":10,"width":0,"height":0}')
w3 = make_win(0, 0, 500, 400)
WinState(w3, "app-zero")
check("zero size not restored", w3.width() == 500 and w3.height() == 400)

# 3. wildly off-screen position is clamped back onto a screen.
scr = QGuiApplication.primaryScreen().availableGeometry()
far_x, far_y = scr.right() + 5000, scr.bottom() + 5000
_state_path("app-off").parent.mkdir(parents=True, exist_ok=True)
_state_path("app-off").write_text(
    '{"x":%d,"y":%d,"width":400,"height":300}' % (far_x, far_y))
w4 = make_win(0, 0, 300, 300)
WinState(w4, "app-off")
onscreen = (w4.x() + 400) > scr.left() and w4.x() < scr.right() \
    and (w4.y() + 300) > scr.top() and w4.y() < scr.bottom()
check("offscreen position clamped", onscreen)

# 4. fixed-size window (min == max) keeps its fixed size.
_state_path("app-fixed").parent.mkdir(parents=True, exist_ok=True)
_state_path("app-fixed").write_text('{"x":10,"y":10,"width":900,"height":900}')
w5 = QWindow()
w5.setGeometry(0, 0, 520, 200)
w5.setMinimumWidth(520)
w5.setMaximumWidth(520)
w5.setMinimumHeight(200)
w5.setMaximumHeight(200)
WinState(w5, "app-fixed")
check("fixed size preserved", w5.width() == 520 and w5.height() == 200)

# 5. missing state file: no crash, window untouched.
w6 = make_win(0, 0, 640, 480)
WinState(w6, "app-none")
check("no state file is a no-op", w6.width() == 640 and w6.height() == 480)

# 6. KWin rules: not written off a Plasma session, written on one, idempotent,
#    and a hand-made rule of his is left untouched.
def kwin_groups():
    p = _kwinrules_path()
    return dict(_parse_kconfig(p.read_text())) if p.exists() else {}

# 6a. no KWin session -> no kwinrulesrc write at all.
w7 = make_win(300, 200, 700, 500)
WinState(w7, "app-kwin")._save()
check("no kwin rule off a Plasma session", not _kwinrules_path().exists())

# Seed a user-owned rule, then turn the session into Plasma.
_kwinrules_path().write_text(
    "[General]\ncount=1\nrules=mine\n\n[mine]\nDescription=his rule\nwmclass=konsole\n")
os.environ["XDG_CURRENT_DESKTOP"] = "KDE"

w8 = make_win(321, 234, 700, 500)
ws8 = WinState(w8, "app-kw2")
ws8._save()
g = kwin_groups()
check("kwin group created", "winstate-app-kw2" in g)
grp = dict(g.get("winstate-app-kw2", []))
check("kwin position recorded", grp.get("position") == "%d,%d" % (w8.x(), w8.y()))
check("kwin wmclass keyed on app_id", grp.get("wmclass") == "app-kw2")
check("kwin apply-initially rule", grp.get("positionrule") == "3")
check("his own rule preserved", dict(g.get("mine", [])).get("wmclass") == "konsole")
gen = dict(g.get("General", []))
listed = [r for r in gen.get("rules", "").split(",") if r]
check("General lists both rules", set(listed) == {"mine", "winstate-app-kw2"}
      and gen.get("count") == "2")

# 6b. second save updates in place, no duplicate group / listing.
w8.setX(999); w8.setY(888)
ws8._save()
g2 = kwin_groups()
gen2 = dict(g2.get("General", []))
listed2 = [r for r in gen2.get("rules", "").split(",") if r]
check("kwin rule updated in place",
      dict(g2["winstate-app-kw2"]).get("position") == "%d,%d" % (w8.x(), w8.y()))
check("no duplicate rule listing",
      listed2.count("winstate-app-kw2") == 1 and gen2.get("count") == "2")

# 6c. the rule is kept off dialogs: normal window types only.
check("kwin rule is normal-windows-only", dict(g2["winstate-app-kw2"]).get("types") == "1")

# 7. WAYLAND: no rule may exist, and the one an older version wrote is deleted.
#    The platform here is offscreen, so stand in for the check itself; and stub
#    the reconfigure call, which would otherwise reach the REAL KWin.
import winstate                                             # noqa: E402
winstate._is_wayland = lambda: True
reconfigures = []
winstate._kwin_reconfigure = lambda: reconfigures.append(1)
os.environ["XDG_CURRENT_DESKTOP"] = "KDE"

w9 = make_win(0, 0, 700, 500)
ws9 = WinState(w9, "app-kw2")          # same app: its stale rule is sitting there
g3 = kwin_groups()
check("wayland drops the stale rule", "winstate-app-kw2" not in g3)
check("wayland delists it too",
      "winstate-app-kw2" not in dict(g3.get("General", [])).get("rules", ""))
check("wayland leaves his own rule alone", "mine" in g3)
check("kwin asked to reconfigure", len(reconfigures) == 1)

ws9._save()
check("wayland writes no rule back", "winstate-app-kw2" not in kwin_groups())

# A second app start finds nothing to drop, so KWin is not poked again.
WinState(make_win(0, 0, 700, 500), "app-kw2")
check("no reconfigure when nothing changed", len(reconfigures) == 1)

# 7b. a Wayland client reads x/y as 0 forever — that must not overwrite a
#     position an X11 session recorded.
import json                                                 # noqa: E402
_state_path("app-wl").parent.mkdir(parents=True, exist_ok=True)
_state_path("app-wl").write_text(json.dumps(
    {"x": 640, "y": 400, "width": 800, "height": 600,
     "maximized": False, "fullscreen": False}))
wA = make_win(0, 0, 800, 600)
wsA = WinState(wA, "app-wl")
wA.resize(900, 700)                    # he resizes it; position he cannot change
wsA._save()
saved = json.loads(_state_path("app-wl").read_text())
check("wayland keeps the recorded position", saved["x"] == 640 and saved["y"] == 400)
check("wayland still records size", saved["width"] == 900 and saved["height"] == 700)

winstate._is_wayland = lambda: False
os.environ.pop("XDG_CURRENT_DESKTOP", None)

print()
if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)
print("all winstate checks passed")
