#!/usr/bin/env python3
"""Look inside a running Vivaldi's UI — in an ISOLATED one, never his.

`pylib/vivaldichrome.py` re-themes Vivaldi by defining the ~90 CSS custom
properties its theme engine sets on `#browser`, and by naming its own element
classes for the Oxygen relief. Both are facts about somebody else's closed
program, so both are READ off a running instance rather than guessed — this is
what reads them.

ISOLATION, and it is the whole point: it starts its own `Xvfb` on a display of
its own, with `WAYLAND_DISPLAY` cleared, a throwaway `--user-data-dir` and a
`--remote-debugging-port`. It never attaches to his browser, never reads his
profile, and puts no window on any screen he has. (His profile is read for
exactly one thing, `--seed-system-themes`, and only the built-in theme list.)

    apps/pylib/tools/vivaldi-probe.py --vars        # the whole colour ladder
    apps/pylib/tools/vivaldi-probe.py --dom         # the UI's structure + classes
    apps/pylib/tools/vivaldi-probe.py --css DIR     # apply a custom.css folder first
    apps/pylib/tools/vivaldi-probe.py --shot OUT.png
    apps/pylib/tools/vivaldi-probe.py --eval 'JS'   # anything else

Needs `Xvfb` (`nix shell nixpkgs#xorg.xvfb`) and, for `--shot`, `import`
(`nix shell nixpkgs#imagemagick`). Both are run from the store, not installed.

WHAT IT ESTABLISHED (2026-08-23, Vivaldi 8.1):

  * the ladder is on `#browser`, ~92 `--color*` plus the `--radius*` family,
  * a theme in `Preferences` is NOT applied by `themes.current` at startup —
    the engine resolves it through `vivaldi.theme.schedule.o_s`, which is why
    `vivaldi-theme.py --prefs` writes both,
  * toolbar icons are `currentColor`, so a dark palette under Vivaldi's own
    `theme-light` classification still inks correctly — the CSS layer alone is
    enough, the theme entry is belt and braces.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

DISPLAY = ":99"
PORT = 9333


# ---- the smallest CDP client that works -------------------------------------
# stdlib only: no websocket package on this box, and one is not worth adding for
# a debugging socket. Frames are always small and always text here.
class WS:
    def __init__(self, url):
        u = urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
             "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
             % (u.path, u.hostname, u.port, key)).encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self.seq = 0

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError("debugger socket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, obj):
        data = json.dumps(obj).encode()
        n, mask = len(data), os.urandom(4)
        head = bytes([0x81])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7f
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            if (b0 & 0x0f) == 1:
                return json.loads(payload.decode())

    def call(self, method, **params):
        self.seq += 1
        self.send({"id": self.seq, "method": method, "params": params})
        while True:
            msg = self.recv()
            if msg.get("id") == self.seq:
                return msg


def ui_target(port=PORT, tries=40):
    """The browser UI's own page — `window.html`, not a web page in a tab."""
    for _ in range(tries):
        try:
            for t in json.load(urlopen("http://127.0.0.1:%d/json/list" % port, timeout=3)):
                if t.get("url", "").endswith("window.html"):
                    return t
        except Exception:                                        # noqa: BLE001
            pass
        time.sleep(0.5)
    raise SystemExit("no Vivaldi UI target on the debugging port")


def evaluate(expr, port=PORT):
    ws = WS(ui_target(port)["webSocketDebuggerUrl"])
    ws.call("Runtime.enable")
    r = ws.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
    res = r.get("result", {}).get("result", {})
    if r.get("result", {}).get("exceptionDetails"):
        raise SystemExit("JS threw: %s" % json.dumps(r["result"]["exceptionDetails"])[:400])
    return res.get("value")


VARS_JS = """
(function(){
  var b = document.getElementById('browser'), cs = getComputedStyle(b), out = {};
  for (var i = 0; i < cs.length; i++){
    var p = cs[i];
    if (p.indexOf('--') === 0) out[p] = cs.getPropertyValue(p).trim();
  }
  out['#browser.className'] = b.className;
  return JSON.stringify(out, null, 1);
})()"""

DOM_JS = """
(function(){
  var out = [];
  (function walk(el, depth){
    if (depth > 5) return;
    for (var i = 0; i < el.children.length; i++){
      var c = el.children[i], r = c.getBoundingClientRect();
      var id = c.id ? '#' + c.id : '';
      var cls = (c.className && c.className.split)
              ? '.' + c.className.trim().split(/\\s+/).slice(0, 4).join('.') : '';
      if (r.width > 30 && r.height > 8)
        out.push('  '.repeat(depth) + c.tagName.toLowerCase() + id + cls +
                 '  [' + Math.round(r.width) + 'x' + Math.round(r.height) + ']');
      walk(c, depth + 1);
    }
  })(document.body, 0);
  return out.join('\\n');
})()"""


class Isolated:
    """Xvfb + a throwaway Vivaldi on it. Torn down in a finally, not at the end
    of the happy path."""

    def __init__(self, workdir: Path, css_dir=None, seed_system=False):
        self.dir = workdir
        self.css_dir = css_dir
        self.seed = seed_system
        self.xvfb = self.viv = None

    def _run(self, pkg, *argv, **kw):
        return subprocess.Popen(["nix", "shell", "nixpkgs#" + pkg, "-c", *argv], **kw)

    def __enter__(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        profile = self.dir / "profile"
        self.xvfb = self._run("xorg.xvfb", "Xvfb", DISPLAY, "-screen", "0", "1400x900x24",
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        env = dict(os.environ, DISPLAY=DISPLAY)
        env.pop("WAYLAND_DISPLAY", None)
        binary = shutil.which("vivaldi") or shutil.which("vivaldi-stable")
        if not binary:
            raise SystemExit("no vivaldi on PATH")
        argv = [binary, "--user-data-dir=%s" % profile, "--ozone-platform=x11",
                "--remote-debugging-port=%d" % PORT, "--no-first-run",
                "--no-default-browser-check", "https://example.com"]
        # First launch shows the welcome flow and renders no toolbar at all, so
        # start once, stop, then start again with the flag it just wrote.
        first = not profile.exists()
        for _ in range(2 if first else 1):
            self.viv = subprocess.Popen(argv, env=env, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
            time.sleep(9)
            if first:
                self._stop_browser()
                self._prepare(profile)
                first = False
        return self

    def _prepare(self, profile):
        prefs = profile / "Default" / "Preferences"
        try:
            data = json.loads(prefs.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if self.css_dir:
            (data.setdefault("vivaldi", {}).setdefault("appearance", {})
             ["css_ui_mods_directory"]) = str(self.css_dir)
        if self.seed:
            # ONLY the built-in theme list, so a themed run resolves ids the way
            # his profile does. No user themes, no history, nothing personal.
            his = Path.home() / ".config" / "vivaldi" / "Default" / "Preferences"
            try:
                system = json.loads(his.read_text(encoding="utf-8"))["vivaldi"]["themes"]["system"]
                data["vivaldi"].setdefault("themes", {})["system"] = system
            except (OSError, ValueError, KeyError):
                pass
        prefs.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")

    def _stop_browser(self):
        if self.viv and self.viv.poll() is None:
            self.viv.terminate()
            for _ in range(30):
                if self.viv.poll() is not None:
                    break
                time.sleep(0.5)
            else:
                self.viv.kill()
        # Chromium flushes Preferences on the way out; a write racing that flush
        # is discarded, which is the whole reason this waits.
        time.sleep(2)

    def shot(self, out: Path):
        self._run("imagemagick", "import", "-display", DISPLAY, "-window", "root",
                  str(out)).wait()
        return out

    def __exit__(self, *exc):
        self._stop_browser()
        if self.xvfb and self.xvfb.poll() is None:
            self.xvfb.terminate()
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vars", action="store_true", help="dump the UI's CSS custom properties")
    ap.add_argument("--dom", action="store_true", help="dump the UI's structure")
    ap.add_argument("--eval", metavar="JS", help="evaluate an expression in the UI")
    ap.add_argument("--css", metavar="DIR", type=Path,
                    help="point the throwaway profile at a custom.css FOLDER first")
    ap.add_argument("--shot", metavar="PNG", type=Path, help="screenshot the isolated display")
    ap.add_argument("--seed-system-themes", action="store_true",
                    help="copy the BUILT-IN theme list out of his profile (nothing else)")
    ap.add_argument("--workdir", type=Path,
                    default=Path(os.environ.get("TMPDIR", "/tmp")) / "vivaldi-probe")
    a = ap.parse_args()
    if not (a.vars or a.dom or a.eval or a.shot):
        a.vars = True
    with Isolated(a.workdir, a.css, a.seed_system_themes) as box:
        if a.vars:
            print(evaluate(VARS_JS))
        if a.dom:
            print(evaluate(DOM_JS))
        if a.eval:
            print(evaluate(a.eval))
        if a.shot:
            print(box.shot(a.shot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
