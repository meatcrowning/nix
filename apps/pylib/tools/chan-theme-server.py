#!/usr/bin/env python3
"""The loopback courier that makes the Vivaldi 4chan re-skin LIVE.

surfer serves this sheet to its own pages over `surferonee://`, in-process.
Vivaldi is somebody else's browser: the only seat is Tampermonkey, and a
userscript has no Python to ask — so until now the CSS was BAKED into the
script and went stale the moment the colour scheme or the wallpaper moved.

This is the Python the userscript can ask. One stdlib HTTP server on
127.0.0.1, rebuilt from the live palette on every request (a build is ~1ms — it
reads kdeglobals or Theme.qml and formats a few KB of CSS), so there is nothing
to invalidate and no hook into wal-set.sh to keep in step:

    GET /chan.css       ->  text/css, ETag: "<crc>"   (304 on If-None-Match)
    GET /scrollbar.css  ->  the desktop's scrollbar (pylib/scrollcss.py):
                            Oxygen's own bar under Plasma, the win31/beveled/
                            flat variant otherwise
    GET /version        ->  {"stamp": ..., "scrollbarStamp": ..., ...}

LOOPBACK ONLY, and that is the whole of its security story: it binds
127.0.0.1, it takes no parameters, and every byte it can emit is a stylesheet
this repo generated. It is NOT a firewall hole — nothing in sys/net has to
learn about it (see AGENTS.md, "Off-LAN: the tailnet": anything loopback-pinned
stays loopback-pinned).

A 4chan page is https, so a plain fetch() to http://127.0.0.1 is blocked as
mixed content — the userscript reaches this through GM_xmlhttpRequest, which
is exactly why it needs `@grant GM_xmlhttpRequest` + `@connect 127.0.0.1`.
Access-Control-Allow-Origin is sent anyway, for a hand `curl` and for any
future caller that is not gmxhr.

    apps/pylib/tools/chan-theme-server.py            # serve on 8791
    apps/pylib/tools/chan-theme-server.py --port N
    apps/pylib/tools/chan-theme-server.py --once     # build once, print, exit
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import chansource                                               # noqa: E402
import scrollcss                                                # noqa: E402


# --------------------------------------------------------------------------- #
#  Which session is this, at REQUEST time
# --------------------------------------------------------------------------- #
# `kdetheme.is_plasma()` reads `XDG_CURRENT_DESKTOP` out of the process
# environment, which is right for an app ("themed by the session that started
# it") and wrong for a daemon: this unit is `WantedBy=default.target`, so it
# starts at login BEFORE the session runs `systemctl --user import-environment`
# and inherits a manager environment that names no desktop at all. is_plasma()
# then reads False for the whole login and a Plasma session gets served the
# Hyprland face — flat, wallpaper-derived, no Oxygen relief — with nothing in
# the log to say so. Measured on `top` 2026-08-23.
#
# So re-read the manager's own store instead of believing what we inherited.
# Cheap (one fork per 15s at most, against a 30s-per-tab poll) and it also
# tracks a session switch under a lingering manager, which a restart-only fix
# would not.
_SESSION_KEYS = ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "KDE_FULL_SESSION")
_ENV_TTL = 15.0
_env_checked = [0.0]


def refresh_session_env(now=None):
    """Pull the session-identifying vars from the systemd user manager."""
    now = time.monotonic() if now is None else now
    if now - _env_checked[0] < _ENV_TTL:
        return
    _env_checked[0] = now
    try:
        out = subprocess.run(["systemctl", "--user", "show-environment"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return
    live = {}
    for line in out.splitlines():
        k, _, v = line.partition("=")
        if k in _SESSION_KEYS:
            live[k] = v
    for k in _SESSION_KEYS:
        if k in live:
            os.environ[k] = live[k]
        else:
            os.environ.pop(k, None)


class Handler(BaseHTTPRequestHandler):
    server_version = "chan-theme/1.0"
    protocol_version = "HTTP/1.1"
    source = None

    def log_message(self, fmt, *a):
        # Quiet by default: this answers a poll every 30s per open 4chan tab,
        # and the journal is not a place to keep that.
        if self.server.verbose:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % a))

    def handle_one_request(self):
        # A poller that hangs up mid-response (a tab closing, gmxhr timing out)
        # is normal here and must not print a traceback into the journal.
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    # path -> the builder behind it. Both rebuild from the live palette per
    # request; neither caches, so a colour-scheme or wallpaper change needs
    # nothing restarted and nothing notified.
    ROUTES = {
        "/chan.css": lambda src: chansource.build_css(src),
        "/": lambda src: chansource.build_css(src),
        "/css": lambda src: chansource.build_css(src),
        "/scrollbar.css": lambda src: scrollcss.build(src),
    }

    def do_GET(self):
        refresh_session_env()
        path = self.path.split("?", 1)[0]
        route = self.ROUTES.get(path)
        if route is None and path != "/version":
            self._send(404, b"chan-theme: /chan.css, /scrollbar.css or /version\n")
            return
        try:
            if path == "/version":
                css, prov = chansource.build_css(self.source)
                bar, barprov = scrollcss.build(self.source)
                body = json.dumps({"stamp": chansource.stamp(css),
                                   "provenance": prov,
                                   "scrollbarStamp": chansource.stamp(bar),
                                   "scrollbarProvenance": barprov}).encode("utf-8")
                self._send(200, body, "application/json",
                           [("ETag", '"%s"' % chansource.stamp(css + bar))])
                return
            css, _prov = route(self.source)
        except SystemExit as e:
            self._send(503, str(e).encode("utf-8"))
            return
        except Exception as e:                                  # noqa: BLE001
            self._send(500, ("%s: %s" % (type(e).__name__, e)).encode("utf-8"))
            return
        tag = '"%s"' % chansource.stamp(css)
        if self.headers.get("If-None-Match") == tag:
            self.send_response(304)
            self.send_header("ETag", tag)
            self.send_header("Content-Length", "0")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return
        self._send(200, css.encode("utf-8"), "text/css; charset=utf-8", [("ETag", tag)])


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=chansource.PORT)
    ap.add_argument("--source", choices=("hypr", "plasma"),
                    help="force the palette source instead of the live session")
    ap.add_argument("--once", action="store_true",
                    help="build the sheet once, print it, exit")
    ap.add_argument("--route", choices=("chan", "scrollbar"), default="chan",
                    help="which sheet --once builds")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    if a.once:
        build = scrollcss.build if a.route == "scrollbar" else chansource.build_css
        css, prov = build(a.source)
        sys.stderr.write("from: %s (stamp %s)\n" % (prov, chansource.stamp(css)))
        sys.stdout.write(css)
        return 0
    Handler.source = a.source
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    srv.verbose = a.verbose
    srv.daemon_threads = True
    sys.stderr.write("chan-theme: http://127.0.0.1:%d/{chan,scrollbar}.css\n" % a.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
