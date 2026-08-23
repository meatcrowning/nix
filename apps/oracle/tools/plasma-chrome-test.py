#!/usr/bin/env python3
"""The Plasma face wears KDE's conventions, not Qt's defaults.

A KDE program is recognised as much by the SHAPE of its chrome as by the style
that paints it, and two of those were missing here until 2026-08-23:

    Settings ▸ Show Menubar     every KDE app has it, on Ctrl+M, and it must
                                stay reachable once the menubar is hidden —
                                a toggle living only in the menubar is a
                                trapdoor. It is added to the WINDOW for that.
    &Edit                       chatter was the only app of ours with no Edit
                                menu: Copy and Select All existed on the
                                transcript's right-click menu and nowhere a
                                menu could show them, so Ctrl+C had no home.

Everything here is read off the REAL window built offscreen — the menus as the
shell built them, the QActions' own enabled state, the resolved style, font and
icons. His session is never touched, no model is loaded, and the offscreen
platform has its own clipboard, so nothing reaches the one he is using.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


def run(**extra):
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_QPA_PLATFORMTHEME"] = "kde"
    env["DESK_SESSION"] = "plasma"
    env["XDG_CURRENT_DESKTOP"] = "KDE"
    for k in ("WAYLAND_DISPLAY", "DISPLAY"):
        env.pop(k, None)
    env.update({k: str(v) for k, v in extra.items()})
    out = subprocess.run([sys.executable, str(APP / "main.py"), "--selftest"],
                         env=env, capture_output=True, text=True, timeout=300)
    return out.stdout + out.stderr


txt = run(ORACLE_CHROME=1, ORACLE_TREE=1, ORACLE_FAKE=1, ORACLE_SELECT=1)
if "root loaded" not in txt:
    print(txt[-2000:])
    print("FAILED: the window never came up")
    sys.exit(1)

check("the window loads clean", "0 QML warning(s)" in txt)

# --- what the style actually resolved to ---------------------------------
m = re.search(r"^style=(\S+) window=(\S+) text=(\S+) icons=(\S+) menubar=(\S+)", txt, re.M)
check("the KStyle, palette and icon theme all resolved", bool(m), "(no ORACLE_TREE line)")
if m:
    style, window, text, icons, menubar = m.groups()
    check("it is wearing a real KStyle, not Fusion", style not in ("fusion", "windows"), style)
    check("the palette came from his colour scheme, not Qt's default light one",
          window.lower() != "#efefef", window)
    check("the icon theme is the desktop's", icons not in ("", "hicolor"), icons)
    check("Show Menubar is an action of the WINDOW, so Ctrl+M works once the "
          "menubar is hidden", menubar == "on-window", menubar)

# --- the menubar, as the shell built it ----------------------------------
menus = {}
cur = None
for line in txt.splitlines():
    if re.match(r"^&|^Se&|^[A-Za-z]+&", line) and not line.startswith(" "):
        cur = line.strip()
        menus[cur] = []
    elif cur and line.startswith("    "):
        menus[cur].append(line.strip())
    elif line.startswith("toolbar"):
        cur = None
titles = list(menus)
check("there is a menubar at all", bool(titles), str(titles))

def rows(title):
    return menus.get(title, [])

check("&File leads", titles[:1] == ["&File"], str(titles))
check("&Edit is second, where KDE puts it", titles[1:2] == ["&Edit"], str(titles))
check("Se&ttings and &Help end it", titles[-2:] == ["Se&ttings", "&Help"], str(titles))
check("File closes with Quit on the platform's shortcut",
      any(r.startswith("&Quit") and "Ctrl+Q" in r for r in rows("&File")))

# --- the Edit menu -------------------------------------------------------
ed = rows("&Edit")
check("Edit has Copy on Ctrl+C", any(r.startswith("Copy ") and "Ctrl+C" in r for r in ed), str(ed))
check("...and Select All on Ctrl+A", any("Select All" in r and "Ctrl+A" in r for r in ed), str(ed))
check("...and a way to take the whole message",
      any("Copy Whole Message" in r for r in ed), str(ed))

# --- Settings: the view toggles lead, and Show Menubar is one of them -----
st = rows("Se&ttings")
check("Settings opens with Show Menubar, on Ctrl+M",
      bool(st) and "Show &Menubar" in st[0] and "Ctrl+M" in st[0], str(st[:1]))
check("...then Show Toolbar and Show Statusbar",
      len(st) > 2 and "Show &Toolbar" in st[1] and "Status&bar" in st[2], str(st[:3]))
check("the app's own rows come AFTER them, not in front",
      any("Base Prompt" in r for r in st[3:]), str(st[:5]))

# --- the rows are honest about what they can do --------------------------
m = re.search(r"^select: selectedText=(.*?) rows=(\{.*\})$", txt, re.M)
check("a real selection was made in a reply", bool(m))
if m:
    sel, state = m.group(1), m.group(2)
    check("the window knows which message holds it", sel not in ("''", '""'), sel)
    check("and Copy / Copy Whole Message / Select All all went live",
          "'copy': True" in state and "'copy-message': True" in state
          and "'select-all': True" in state, state)

# with NOTHING selected they must be dead rather than silently doing nothing
plain = run(ORACLE_CHROME=1, ORACLE_FAKE=1)
ed0 = []
cur = None
for line in plain.splitlines():
    if line.startswith("&Edit"):
        cur = True
    elif cur and line.startswith("    "):
        ed0.append(line.strip())
    elif cur and not line.startswith("    "):
        break
check("with nothing selected every Edit row is disabled, not dead-looking",
      bool(ed0) and all("(disabled)" in r for r in ed0 if r != "---"), str(ed0))

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
