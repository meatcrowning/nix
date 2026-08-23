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


def run(session, **extra):
    env = dict(os.environ)
    env["DESK_SESSION"] = session
    env.update(extra)
    env["QT_QPA_PLATFORMTHEME"] = "kde"
    env["PLAYER_MENUS"] = "1"
    env["PLAYER_FACES"] = "1"
    # A page with one of every swapped control on it, so the face check below
    # has something to look at.
    env["PLAYER_VIEW"] = "playlists"
    # QT_QPA_PLATFORMTHEME=kde is NOT optional: without a KDE platform theme the
    # widgets take Qt's default light palette while the QML takes his dark
    # scheme, and the window renders as an empty-looking toolbar with invisible
    # labels — a bug in the harness, not in the app (apps/AGENTS.md).
    out = subprocess.run([sys.executable, str(APP / "main.py"), "--selftest"],
                         env=env, capture_output=True, text=True, timeout=120)
    # stderr too: kdeshell's "publishes no buttonsChanged" warning is the only
    # sign of a chrome that builds correctly and then never updates again.
    return out.stdout + out.stderr


plasma = run("plasma")
hypr = run("hypr")
# ...and the same window with a queue under it and the transport running, which
# is the ONLY way to see the chrome follow the app's state.
busy = run("plasma", PLAYER_STATEPOKE="1,2,3", PLAYER_STATEPOKE_PLAYING="1")

print("player's Plasma chrome")

# ---- the menubar --------------------------------------------------------
# The menubar headings: the un-indented lines from the first menu up to the
# toolbar heading. Anchored rather than filtered, because the child prints its
# own lines too (the library's scan summary, the `face` dump).
lines = plasma.splitlines()
head = next(i for i, ln in enumerate(lines) if ln.startswith("&File"))
tail = next(i for i, ln in enumerate(lines) if ln == "toolbar")
menus = [ln for ln in lines[head:tail] if ln and not ln.startswith(" ")]
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


def verb(row):
    """A row's verb, with the checkbox gutter off the front. A checkable row
    reads `[x] Playlists`, and which one is checked depends on the page the
    harness happens to be on."""
    return row[4:] if row[:1] == "[" else row


view = section(plasma, "&View")
playback = section(plasma, "&Playback")
top = section(plasma, "toolbar")
transport = section(plasma, "toolbar[transport]")

# ---- the menus are the COMPLETE set, the toolbar the primary verbs -------
for name in ("Albums", "Playlists"):
    check(f"{name} is in the View menu",
          any(verb(r).startswith(name) for r in view), str(view))
    check(f"{name} is on the toolbar",
          any(verb(r).startswith(name) for r in top), str(top))
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
for name in ("Previous Track", "Play", "Next Track", "Favourite", "Repeat", "Shuffle"):
    check(f"{name} is on the transport bar",
          any(verb(r).startswith(name) for r in transport), str(transport))
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

# ---- THE CHROME FOLLOWS THE APP'S STATE ---------------------------------
# The case that was silently broken: `bind_chrome` hangs its refresh on the vtb
# bridge's `buttonsChanged`, and player's `Titlebar` published no such signal —
# so the menubar and both toolbars were built once at startup and then FROZE.
# Play never became Pause and the transport stayed greyed by the empty queue it
# had started with, with nothing failing and nothing warning.
busy_transport = section(busy, "toolbar[transport]")
busy_playback = section(busy, "&Playback")
check("a queue enables the transport rows",
      busy_transport and not any(r.endswith("(disabled)") for r in busy_transport
                                 if r.startswith(("Previous Track", "Next Track"))),
      str(busy_transport))
check("playing turns Play into Pause on the bar",
      any(r.startswith("Pause") for r in busy_transport)
      and not any(r.startswith("Play") for r in busy_transport),
      str(busy_transport))
check("...and in the Playback menu, off the same QAction",
      any(r.startswith("Pause") for r in busy_playback), str(busy_playback))
check("the status bar's right slot carries the queue position",
      "'1 / 3'" in busy, [ln for ln in busy.splitlines() if ln.startswith("statusbar")])
check("kdeshell did not have to fall back to polling the chrome",
      "publishes no buttonsChanged" not in plasma, "see stderr")

# ---- the Settings menu owns the bars ------------------------------------
settings = section(plasma, "Se&ttings")
check("Configure player… is in Settings",
      any(r.startswith("Configure player") for r in settings), str(settings))
for row in ("Show &Toolbar", "Show Transport Bar", "Show Status&bar"):
    check(f"Settings can hide {row!r}",
          any(row in r for r in settings), str(settings))

# ---- the +plasma file selector actually took --------------------------
# A `QQmlFileSelector` with no owner is collected moments after it is made, and
# every component then loads its UNSELECTED file — silently, with no error and
# no warning. Each variant carries `property string face: "plasma"` so that
# failure is detectable at all (kdeshell.select_plasma_files).
faces = dict(ln[5:].split(" = ", 1) for ln in plasma.splitlines()
             if ln.startswith("face ") and " = " in ln)
for comp in ("HeaderButton", "SelectButton", "Slider", "CtxMenu",
             "EditField", "SheetFrame"):
    check(f"{comp} is the KDE variant under Plasma",
          faces.get(comp) == "plasma", str(faces))
check("...and nothing is swapped under Hyprland",
      "face: none found" in hypr,
      "\n".join(ln for ln in hypr.splitlines() if ln.startswith("face")))

# ---- and NONE of it exists under Hyprland -------------------------------
check("a Hyprland session builds no KDE chrome at all",
      "toolbar[transport]" not in hypr and "&Playback" not in hypr,
      hypr.strip().splitlines()[-1:] and hypr.strip().splitlines()[-1])

# ---- no titlebar glyph reaches a real KDE button ------------------------
# `HeaderButton`'s label is written for the pixel face, where an affordance IS a
# character ("> play", "x close", a bare "x"). On the styled Button the Plasma
# twin draws, that vocabulary is the imitation the whole face exists to drop, so
# a glyph label has to state `plainLabel`/`iconName` (or `iconOnly`) beside it.
# Checked in the SOURCE rather than in a render: a button on a page nobody
# opened in this run is exactly the one that would be missed.
GLYPHS = ("> ", "+ ", "x ", "< ")
for qml in sorted((APP / "qml").glob("*.qml")):
    body = qml.read_text(encoding="utf-8")
    lines = body.splitlines()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("label: \""):
            continue
        lit = s[8:].split("\"")[0]
        if not (lit.startswith(GLYPHS) or lit in ("x", "-", "+")):
            continue
        near = " ".join(lines[max(0, i - 1):i + 4])
        check(f"{qml.name}: {lit!r} says what a KDE button should read",
              "plainLabel:" in near or "iconOnly:" in near, near.strip())

print(("FAILED: " + ", ".join(fails)) if fails else "all ok")
sys.exit(1 if fails else 0)
