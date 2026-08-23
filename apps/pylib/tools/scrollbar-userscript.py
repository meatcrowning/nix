#!/usr/bin/env python3
"""Generate the Tampermonkey userscript that puts this desktop's scrollbar on
every page in Vivaldi.

Chromium never asks Qt or GTK for a scrollbar; it paints its own in Aura. So a
page's bar is the one control `qmlcommon/VScroll.qml` cannot reach, and in
Vivaldi neither can a Qt style: no Stylus, no theme bridge, only Tampermonkey.
`pylib/scrollcss.py` builds the sheet (Oxygen's own bar under Plasma, the
desktop's win31/beveled/flat variant otherwise) and this puts it where Vivaldi
will read it. Both halves are LIVE against the loopback courier the same way
the 4chan sheet is — see `pylib/userscript.py`.

This writes the PAGE half only: `~/.local/share/chan-theme/desktop-scrollbar.user.js`,
re-adopted within POLL_SECONDS of a palette change. Vivaldi's OWN interface is
a Chromium page too and takes the same sheet, but through a `custom.css` —
`tools/vivaldi-theme.py` writes that file, and writes this sheet into it, so
there is exactly one writer of it.

    apps/pylib/tools/scrollbar-userscript.py            # write the userscript
    apps/pylib/tools/scrollbar-userscript.py --css      # print the CSS only
    apps/pylib/tools/scrollbar-userscript.py --source hypr|plasma
    apps/pylib/tools/scrollbar-userscript.py --style win31|beveled|flat
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import chansource                                               # noqa: E402
import scrollcss                                                # noqa: E402
import userscript                                               # noqa: E402

DATA = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
OUT = DATA / "chan-theme" / "desktop-scrollbar.user.js"

# Everything http(s), including a local file:// page — the desktop's scrollbar
# is not a per-site opinion.
MATCHES = ("*://*/*", "file:///*")


def build(source=None, style=None, path=OUT, port=None):
    css, prov = scrollcss.build(source, style)
    port = port or chansource.PORT
    version = "1.0.%s" % chansource.stamp(css)
    return userscript.build(
        name="desktop scrollbar",
        description=("Draws every page's scrollbar as this desktop's (%s), "
                     "polling the loopback courier." % prov),
        matches=MATCHES, css=css, version=version,
        url="http://127.0.0.1:%d/scrollbar.css" % port,
        key="__deskScrollbar", style_id="desk-scrollbar",
        path=path, tool="scrollbar-userscript.py"), prov


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=("hypr", "plasma"),
                    help="force the palette source instead of the live session")
    ap.add_argument("--style", choices=scrollcss.STYLES,
                    help="force a desktop variant instead of the settings pick")
    ap.add_argument("--css", action="store_true", help="print the CSS, write nothing")
    ap.add_argument("--stdout", action="store_true", help="print the userscript")
    ap.add_argument("--port", type=int, default=chansource.PORT)
    ap.add_argument("-o", "--out", type=Path, default=OUT)
    a = ap.parse_args()

    if a.css:
        print(scrollcss.build(a.source, a.style)[0])
        return 0
    text, prov = build(a.source, a.style, a.out, a.port)
    if a.stdout:
        sys.stdout.write(text)
        return 0

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(text, encoding="utf-8")
    print("%s\n  live from: http://127.0.0.1:%d/scrollbar.css (chan-theme-server)"
          "\n  embedded fallback: %s\n  open file://%s in Vivaldi to (re)install"
          % (a.out, a.port, prov, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
