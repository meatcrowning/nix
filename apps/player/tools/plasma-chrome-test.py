#!/usr/bin/env python3
"""Harness for player's Plasma face — the menubar and two toolbars.

    player-qtenv python3 apps/player/tools/plasma-chrome-test.py

It runs `main.py --selftest` in a child, once with `DESK_SESSION=plasma` and
once with `hypr`, and asserts on `kdeshell.dump_chrome()`. That indirection is
the point: a menu is not on screen until it is opened, so no render can show
what is in one, and the child is what actually builds the real QMenuBar and
QToolBars out of `Root.qml`'s `tbButtons` (apps/AGENTS.md → kdeshell).

The child is OFFSCREEN and deliberately not a whole player: `--selftest` starts
no MPRIS name, binds no queue socket, runs no library scan and saves no state,
so it cannot disturb the running player or his session (~/nix/AGENTS.md).

The album/playlist browser buttons and Randomize occupy the main toolbar;
search belongs to the album browser, and a native timing widget follows the
buttons. Transport stays on the bottom toolbar.
"""

import os
import subprocess
import sys
import tempfile
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
    # No real session, database, mpv, scanner, metadata network, or saved preferences.
    with tempfile.TemporaryDirectory(prefix="player-chrome-") as scratch:
        root = Path(scratch)
        for key in ('DATA', 'STATE', 'CONFIG', 'CACHE', 'RUNTIME'):
            path = root/key; path.mkdir(mode=0o700)
            env['XDG_RUNTIME_DIR' if key == 'RUNTIME' else 'XDG_'+key+'_HOME'] = str(path)
        (root/'mpv.py').write_text("class MPV:\n"
            "    def __init__(self, **kw): self.volume=100; self.pause=True; self.playlist_count=0; self.playlist_pos=0\n"
            "    def property_observer(self, name): return lambda fn: fn\n"
            "    def command(self, *args): pass\n"
            "    def __setitem__(self, key, value): pass\n")
        env.update(PYTHONPATH=str(root), QT_QPA_PLATFORM='offscreen',
                   QT_QPA_PLATFORMTHEME='', QT_STYLE_OVERRIDE='Fusion', QT_QUICK_CONTROLS_STYLE='Basic',
                   DBUS_SESSION_BUS_ADDRESS='unix:path='+str(root/'no-bus'),
                   PIPEWIRE_REMOTE='/dev/null', PULSE_SERVER='unix:'+str(root/'no-pulse'),
                   PLAYER_LIBRARY_ROOT=str(root/'music'), LASTFM_CONFIG=str(root/'no-lastfm'))
        for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE'):
            env.pop(key, None)
        code = f"""
import sys
sys.path.insert(0, {str(APP)!r})
import main
main.AutoScanner=lambda *args: None
main.Bridge._request_now_info=lambda self: None
con=main.open_db()
for i in range(1,4):
    con.execute('INSERT INTO tracks (id,path,mtime,size,added_at,title) VALUES (?,?,0,0,0,?)',
                (i, {scratch!r}+'/track'+str(i)+'.flac', 'fixture '+str(i)))
con.commit()
con.close()
main.main()
"""
        out = subprocess.run([sys.executable, '-c', code, '--selftest'],
                             env=env, capture_output=True, text=True, timeout=40)
        assert out.returncode == 0, out.stdout + out.stderr
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
      menus == ["&File", "&View", "&Playback", "&Visualizer", "Se&ttings", "&Help"], str(menus))


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
    """A row's verb, with the checkbox gutter off the front and the mnemonic
    marker out of the middle. A checkable row reads `[x] P&laylists`, and
    which one is checked depends on the page the harness happens to be on."""
    return (row[4:] if row[:1] == "[" else row).replace("&", "")


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
check("only browser modes remain in navigation",
      not any(verb(r).startswith(("Now Playing", "Visualizer")) for r in top + view), str(top + view))
check("Randomize is on the toolbar", any(verb(r).startswith("Randomize") for r in top), str(top))

# ---- sort moved beside the album index; its menu fallback remains ----------
check("sort is not duplicated on the top toolbar",
      not any("sort:" in r.replace("&", "").lower() for r in top), str(top))
check("sort remains in the View menu", any(r.startswith("Sort by ") for r in view),
      str(view))
index_source = (APP / "qml" / "AlbumIndex.qml").read_text(encoding="utf-8")
for label in ("year", "artist", "album title", "date added", "play count", "rating"):
    check(f"album index offers {label}", f'label: "{label}"' in index_source)
check("album index owns a separate direction control",
      'view-sort-descending' in index_source and 'view-sort-ascending' in index_source)
check("no two-character titlebar cell reached the chrome",
      not any(r.strip() in ("yr", "ar", "al", "fs", "st", "<<", ">>") for r in top + view),
      str(top + view))

# ---- the toolbar names its buttons, as Konsole's does -------------------
check("the toolbar's buttons wear their names beside the icons",
      "barstyle: text-beside-icon" in plasma,
      [ln for ln in plasma.splitlines() if ln.startswith("barstyle:")] or "(none)")

# ---- every top-bar row wears an Alt-letter, and no two share one --------
# The underline is what says a button HAS a shortcut, so a letter two rows
# both claim — or one the menubar's own titles already answer to — is worse
# than none (docs/DESIGN.md §10).
import re as _re
bar_letters = [m.group(1).upper() for r in top
               for m in [_re.search(r"&(\w)", r)] if m]
menu_letters = [m.group(1).upper() for t in menus
                for m in [_re.search(r"&(\w)", t)] if m]
check("every named row on the top toolbar has one",
      len(bar_letters) == len([r for r in top if not r.startswith("<QWidget")
                               and not r.startswith("<QLineEdit") and r != "---"]),
      str(top))
check("no two rows claim the same letter",
      len(set(bar_letters)) == len(bar_letters), str(bar_letters))
check("...and none of them is a menubar title's",
      not (set(bar_letters) & set(menu_letters)),
      str(sorted(set(bar_letters))) + " vs " + str(sorted(set(menu_letters))))

# Search stays with the album browser, and timing occupies the native toolbar.
check("the top toolbar has timing instead of a search field",
      not any(r.startswith("<QLineEdit") for r in top) and "<QWidget>" in top, str(top))
check("Find… is still in the View menu", any(r.startswith("Find…") for r in view),
      str(view))

# ---- the transport bar --------------------------------------------------
for name in ("Previous Track", "Play", "Next Track", "Favourite", "Repeat", "Shuffle"):
    check(f"{name} is on the transport bar",
          any(verb(r).startswith(name) for r in transport), str(transport))
# ---- the repeat row says WHICH repeat is on -----------------------------
# It used to wear one icon for all three modes, so clicking it changed nothing
# a Plasma user could see (the lit state alone cannot separate off from all).
loop_icons = {}
for mode in ("0", "1", "2"):
    dump = run("plasma", PLAYER_STATEPOKE="1,2,3", PLAYER_STATEPOKE_LOOP=mode)
    row = next((r for r in section(dump, "icons") if r.startswith("loop: ")), "")
    loop_icons[mode] = row[len("loop: "):]
check("repeat-track wears its own icon",
      loop_icons["1"] and loop_icons["1"] != loop_icons["0"], str(loop_icons))
check("repeat-all and off share the icon, separated by the check",
      loop_icons["0"] and loop_icons["2"] == loop_icons["0"], str(loop_icons))
for mode, word in (("1", "Repeat Track"), ("2", "Repeat All"), ("0", "Repeat")):
    dump = run("plasma", PLAYER_STATEPOKE="1,2,3", PLAYER_STATEPOKE_LOOP=mode)
    check(f"the Playback row reads {word!r} in mode {mode}",
          any(verb(r) == word for r in section(dump, "&Playback")),
          str(section(dump, "&Playback")))

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
check("the redundant status bar stays disabled",
      "Show Status&bar" not in section(plasma, "Se&ttings"),
      str(section(plasma, "Se&ttings")))
check("the redundant status bar is not attached to the window",
      "statusbar: absent" in plasma,
      next((r for r in plasma.splitlines() if r.startswith("statusbar:")), "missing"))
check("kdeshell did not have to fall back to polling the chrome",
      "publishes no buttonsChanged" not in plasma, "see stderr")

# ---- the Settings menu owns the bars ------------------------------------
settings = section(plasma, "Se&ttings")
check("Configure player… is in Settings",
      any(r.startswith("Configure player") for r in settings), str(settings))
for row in ("Show &Toolbar", "Show Transport Bar"):
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
        # Every line of the button's OWN block, not a fixed window: a comment
        # explaining the button pushes its `iconName` past a four-line peek,
        # and the check then failed on a button that states everything it
        # should (SettingsPanel's close 'x', 2026-08-23).
        end = i + 1
        while end < len(lines) and lines[end].strip() not in ("}", "};"):
            end += 1
        near = " ".join(lines[max(0, i - 1):end])
        check(f"{qml.name}: {lit!r} says what a KDE button should read",
              "plainLabel:" in near or "iconOnly:" in near, near.strip())

print(("FAILED: " + ", ".join(fails)) if fails else "all ok")
sys.exit(1 if fails else 0)
