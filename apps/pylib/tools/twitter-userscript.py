#!/usr/bin/env python3
"""Generate the live desktop-palette Tampermonkey theme for Twitter/X."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import chansource  # noqa: E402
import twittertheme  # noqa: E402
import userscript  # noqa: E402

OUT = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) \
    / "chan-theme" / "desktop-twitter.user.js"


def build(source=None, path=OUT, port=None):
    pal, prov = chansource.palette(source)
    sheet = twittertheme.css(pal.__getitem__)
    port = port or chansource.PORT
    version = userscript.source_version(
        (HERE.parent / "twittertheme.py", HERE.parent / "chansource.py",
         HERE.parent / "userscript.py", HERE / "twitter-userscript.py"), major=1)
    return userscript.build(
        name="desktop Twitter/X", description=("Re-skins Twitter/X to this desktop's LIVE "
                                                "palette (%s), polling the loopback courier." % prov),
        matches=("*://twitter.com/*", "*://*.twitter.com/*", "*://x.com/*", "*://*.x.com/*"),
        css=sheet, version=version, url="http://127.0.0.1:%d/twitter.css" % port,
        update_url="http://127.0.0.1:%d/twitter.meta.js" % port,
        download_url="http://127.0.0.1:%d/twitter.user.js" % port,
        key="__deskTwitterTheme", style_id="desk-twitter-theme", gate=None,
        path=path, tool="twitter-userscript.py"), prov


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=("hypr", "plasma"))
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--css", action="store_true")
    ap.add_argument("--port", type=int, default=chansource.PORT)
    ap.add_argument("-o", "--out", type=Path, default=OUT)
    a = ap.parse_args()
    if a.css:
        pal, _ = chansource.palette(a.source)
        print(twittertheme.css(pal.__getitem__))
        return 0
    text, prov = build(a.source, a.out, a.port)
    if a.stdout:
        sys.stdout.write(text)
        return 0
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(text, encoding="utf-8")
    print("%s\n  live from: http://127.0.0.1:%d/twitter.css (%s)\n  install via Tampermonkey: "
          "http://127.0.0.1:%d/twitter.user.js" % (a.out, a.port, prov, a.port))


if __name__ == "__main__":
    raise SystemExit(main())
