#!/usr/bin/env python3
"""Generate the Tampermonkey userscript that puts this desktop's look on 4chan
in Vivaldi.

surfer gets the OneeChan override sheet through its own `surferonee://`
courier, in-process, live. Vivaldi cannot: it is somebody else's browser, it
has no Stylus, and the only injection seat available is Tampermonkey — where
OneeChan itself already lives. So the same sheet (`pylib/chantheme.py`, shared
verbatim, which is why that module is Qt-free) goes into a userscript here.

NOT baked-only any more. The script asks `tools/chan-theme-server.py` — a
loopback courier on 127.0.0.1 — for the current sheet, and re-adopts it when
the ETag moves, so a colour-scheme or wallpaper change repaints an OPEN 4chan
tab within the poll interval and needs no regeneration at all. That whole
runtime is `pylib/userscript.py`, shared with the scrollbar script
(`scrollbar-userscript.py`) so the two cannot drift; all this file decides is
the sheet, the match rules and the OneeChan gate.

Re-run this only when the SHEET (`pylib/chantheme.py`) or this generator
changes — not for a palette change. Tampermonkey picks the new file up on its
next update check (or reinstall it by hand).

    apps/pylib/tools/chan-userscript.py            # write it, print the path
    apps/pylib/tools/chan-userscript.py --stdout   # print the script instead
    apps/pylib/tools/chan-userscript.py --css      # just the CSS
    apps/pylib/tools/chan-userscript.py --source hypr|plasma

The palette source follows the same rule the apps do (`kdetheme.is_plasma`):
the KDE colour scheme in a Plasma session — with the KStyle's gradients and
bevels on top when the style draws them — and the panel's wallpaper palette in
the Hyprland one, where DESIGN.md §2's "no gradients" holds and the sheet stays
flat. `--source` forces either, for a look at the other face; it also pins the
courier the script polls, so a `--source`-built script asks for that same face.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import chansource                                               # noqa: E402
import userscript                                               # noqa: E402

build_css = chansource.build_css
panel_palette = chansource.panel_palette
PANEL_THEME = chansource.PANEL_THEME
OUT = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) \
    / "chan-theme" / "desktop-4chan.user.js"


def build(source=None, path=OUT, port=None):
    css, prov = build_css(source)
    port = port or chansource.PORT
    # Moves when the SCRIPT does — the sheet, this generator or the shared
    # runtime — and never backwards, which is what Tampermonkey's updater
    # needs. A palette change moves nothing here on purpose: the installed
    # script polls the courier for that and must not be reinstalled for it.
    version = userscript.source_version(
        (HERE.parent / "chantheme.py", HERE.parent / "chansource.py",
         HERE.parent / "userscript.py", HERE / "chan-userscript.py"), major=3)
    return userscript.build(
        name="desktop 4chan",
        description=("Re-skins OneeChan's 4chan theme to this desktop's LIVE "
                     "palette (%s), polling the loopback courier." % prov),
        matches=("*://boards.4chan.org/*", "*://boards.4channel.org/*"),
        css=css, version=version,
        url="http://127.0.0.1:%d/chan.css" % port,
        update_url="http://127.0.0.1:%d/chan.user.js" % port,
        key="__deskChanTheme", style_id="desk-chan-theme",
        gate="oneechan", path=path, tool="chan-userscript.py"), prov


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=("hypr", "plasma"),
                    help="force the palette source instead of the live session")
    ap.add_argument("--stdout", action="store_true", help="print, do not write")
    ap.add_argument("--css", action="store_true", help="print the CSS only")
    ap.add_argument("--port", type=int, default=chansource.PORT,
                    help="the loopback courier the script polls")
    ap.add_argument("-o", "--out", type=Path, default=OUT)
    a = ap.parse_args()
    if a.css:
        print(build_css(a.source)[0])
        return 0
    text, prov = build(a.source, a.out, a.port)
    if a.stdout:
        sys.stdout.write(text)
        return 0
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(text, encoding="utf-8")
    print("%s\n  live from: http://127.0.0.1:%d/chan.css (chan-theme-server)"
          "\n  embedded fallback: %s"
          "\n  install ONCE from http://127.0.0.1:%d/chan.user.js — from THERE it"
          "\n  auto-updates; a copy installed from file:// never will."
          % (a.out, a.port, prov, a.port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
