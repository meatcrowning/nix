#!/usr/bin/env python3
"""Harness for player's Plasma face — the menubar, the two toolbars, the status bar.

    player-qtenv python3 apps/player/tools/plasma-chrome-test.py

It runs `main.py --selftest` in a child, once with `DESK_SESSION=plasma` and
once with `hypr`, and asserts on `kdeshell.dump_chrome()`. That indirection is
the point: a menu is not on screen until it is opened, so no render can show
what is in one, and the child is what actually builds the real QMenuBar and
QToolBars out of `Root.qml`'s `tbButtons` (apps/AGENTS.md → kdeshell).

The child is OFFSCREEN and deliberately not a whole player: `--selftest` starts
no MPRIS name, binds no queue socket, runs no library scan and saves no state,
so it cannot disturb the running player or his session (~/nix/AGENTS.md).

It replaces `viewbar-test.py`, which tested `ViewBar.qml` — a QML imitation of a
view toolbar. That file is gone; the three views, the sort cycler and the finder
are real toolbar rows and a real QLineEdit now, and this is what checks them.

Covers: that the menus are KDE's vocabulary in KDE's order with File first and
Settings/Help last; that the three views are on the top toolbar AND still in the
View menu (the menus are the complete set, the toolbar is the primary verbs);
that the sort row carries the full word rather than the titlebar's two-character
cell; that the finder is a QLineEdit on that bar; that the transport bar carries
the six playback verbs and the seek widget; that a verb with nothing to act on
is DISABLED rather than absent; and that in a Hyprland session none of it is
built at all.
"""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent

fails = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        fails.append(name)


def run(session):
    env = dict(os.environ)
    env["DESK_SESSION"] = session
    env["QT_QPA_PLATFORMTHEME"] = "kde"
    env["PLAYER_MENUS"] = "1"
    # QT_QPA_PLATFORMTHEME=kde is NOT optional: without a KDE platform theme the
    # widgets take Qt's default light palette while the QML takes his dark
    # scheme, and the window renders as an empty-looking toolbar with invisible
    # labels — a bug in the harness, not in the app (apps/AGENTS.md).
    out = subprocess.run([sys.executable, str(APP / "main.py"), "--selftest"],
                         env=env, capture_output=True, text=True, timeout=120)
    return out.stdout


plasma = run("plasma")
hypr = run("hypr")

print("player's Plasma chrome")

# ---- the menubar --------------------------------------------------------
menus = [ln for ln in plasma.splitlines() if ln and not ln.startswith((" ", "toolbar", "statusbar", "selftest"))]
check("File first, Help last", menus[:1] == ["&File"] and menus[-1:] == ["&Help"],
      str(menus))
check("the KDE vocabulary, with the app's own group before Settings",
      menus == ["&File", "&View", "&Playback", "Se&ttings", "&Help"], str(menus))


def section(text, head):
    """The indented rows under one heading of `dump_chrome`."""
    lines = text.splitlines()
    try:
        i = lines.index(head)
    except ValueError:
        return []
    out = []
    for ln in lines[i + 1:]:
        if not ln.startswith("    "):
            break
        out.append(ln.strip())
    return out


view = section(plasma, "&View")
playback = section(plasma, "&Playback")
top = section(plasma, "toolbar")
transport = section(plasma, "toolbar[transport]")

# ---- the menus are the COMPLETE set, the toolbar the primary verbs -------
for verb in ("Albums", "Playlists"):
    check(f"{verb} is in the View menu", any(r.startswith(verb) for r in view),
          str(view))
    check(f"{verb} is on the toolbar", any(r.startswith(verb) for r in top),
          str(top))
check("Now Playing is a radio row (checked, not just present)",
      any(r.startswith("[x] Now Playing") or r.startswith("[ ] Now Playing")
          for r in view), str(view))

# ---- the sort row carries the WORD, not the titlebar's two-character cell -
check("sort names the mode in full on the toolbar",
      any(r.startswith("<QToolButton 'sort: ") for r in top), str(top))
check("...and in the View menu", any(r.startswith("Sort by ") for r in view),
      str(view))
check("no two-character titlebar cell reached the chrome",
      not any(r.strip() in ("yr", "ar", "al", "fs", "st", "<<", ">>") for r in top + view),
      str(top + view))

# ---- the finder is a real field, at the right-hand end ------------------
check("the finder is a QLineEdit on the toolbar",
      any(r.startswith("<QLineEdit") for r in top), str(top))
check("...behind a stretch, so it sits against the right edge",
      any(r == "<QWidget>" for r in top)
      and top.index("<QWidget>") < [i for i, r in enumerate(top)
                                    if r.startswith("<QLineEdit")][0],
      str(top))
check("Find… is still in the View menu", any(r.startswith("Find…") for r in view),
      str(view))

# ---- the transport bar --------------------------------------------------
for verb in ("Previous Track", "Play", "Next Track", "Favourite", "Repeat", "Shuffle"):
    check(f"{verb} is on the transport bar",
          any(r.startswith(verb) for r in transport), str(transport))
check("the seek widget is on the transport bar",
      any(r.startswith("<TransportSeek") for r in transport), str(transport))
check("every playback verb is also in the Playback menu",
      all(any(r.startswith(v) for r in playback)
          for v in ("Previous Track", "Play", "Next Track", "Favourite",
                    "Repeat", "Shuffle")), str(playback))

# ---- a verb with nothing to act on is DISABLED, not absent --------------
# The selftest plays nothing, so the transport has an empty queue under it.
check("with an empty queue the transport is disabled, not missing",
      all(r.endswith("(disabled)")
          for r in transport if r.startswith(("Previous Track", "Play", "Next Track"))),
      str(transport))

# ---- the Settings menu owns the bars ------------------------------------
settings = section(plasma, "Se&ttings")
check("Configure player… is in Settings",
      any(r.startswith("Configure player") for r in settings), str(settings))
for row in ("Show &Toolbar", "Show Transport Bar", "Show Status&bar"):
    check(f"Settings can hide {row!r}",
          any(row in r for r in settings), str(settings))

# ---- and NONE of it exists under Hyprland -------------------------------
check("a Hyprland session builds no KDE chrome at all",
      "toolbar[transport]" not in hypr and "&Playback" not in hypr,
      hypr.strip().splitlines()[-1:] and hypr.strip().splitlines()[-1])

print(("FAILED: " + ", ".join(fails)) if fails else "all ok")
sys.exit(1 if fails else 0)
