#!/usr/bin/env python3
"""Offscreen booru test against a loopback Danbooru fixture.

Serves posts/counts/wiki/related JSON and generated PNG thumbnails on
127.0.0.1, points booru at it with BOORU_BASE_URL, and runs `main.py
--selftest` in both faces with scratch XDG dirs, so nothing reaches the
network, the user's cache, config or Pictures.

  booru-qtenv python3 apps/booru/tools/booru-test.py [--shot DIR]
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
MAIN = HERE.parent / "main.py"


def png(w, h, rgb):
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_posts(base, page, n=40, pages=2):
    if page > pages:
        return []
    out = []
    for i in range(n):
        pid = 1000 - (page - 1) * n - i
        out.append({
            "id": pid, "rating": "g", "score": pid % 50, "source": "https://example.invalid/%d" % pid,
            "image_width": 800, "image_height": 600, "file_ext": "png",
            "tag_string_general": "1girl long_hair smile" + (" blacklisted_tag" if i == 3 else ""),
            "tag_string_character": "hatsune_miku", "tag_string_copyright": "vocaloid",
            "tag_string_artist": "someone", "tag_string_meta": "highres",
            "preview_file_url": f"{base}/img/p{pid}.png",
            "large_file_url": f"{base}/img/s{pid}.png",
            "file_url": f"{base}/img/o{pid}.png",
        })
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype="application/json", code=200):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        base = "http://%s:%d" % self.server.server_address
        if "booru/" not in self.headers.get("User-Agent", ""):
            return self.send({"message": "bad user agent"}, code=403)
        if u.path == "/posts.json":
            return self.send(make_posts(base, int(q.get("page", 1)), int(q.get("limit", 40))))
        if u.path == "/counts/posts.json":
            return self.send({"counts": {"posts": 80}})
        if u.path == "/wiki_pages.json":
            t = q.get("search[title]", "")
            return self.send([{"title": t, "body": "h4. About\r\nA [[VOCALOID]] by "
                               "[[Crypton Future Media|Crypton]]. [b]bold[/b] <img src=x>"}])
        if u.path == "/related_tag.json":
            return self.send({"related_tags": [
                {"tag": {"name": "twintails", "category": 0, "post_count": 10}},
                {"tag": {"name": "aqua_hair", "category": 0, "post_count": 9}}]})
        if u.path.startswith("/img/"):
            return self.send(png(180 if "/p" in u.path else 800, 135 if "/p" in u.path else 600,
                                 (200, 80, 40)), "image/png")
        self.send({"message": "not found"}, code=404)


def main():
    shot_dir = None
    if "--shot" in sys.argv:
        shot_dir = Path(sys.argv[sys.argv.index("--shot") + 1])
        shot_dir.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    failures = []
    with tempfile.TemporaryDirectory(prefix="booru-test-") as tmp:
        # No <servicedir>: nothing on the private bus is ever ACTIVATED. With
        # the stock session config the platform theme starts
        # xdg-desktop-portal-kde and ksecretd, which outlive the bus.
        bus_conf = Path(tmp, "bus.conf")
        bus_conf.write_text(
            '<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"'
            ' "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">'
            '<busconfig><type>session</type><listen>unix:tmpdir=%s</listen>'
            '<auth>EXTERNAL</auth><policy context="default"><allow send_destination="*"/>'
            '<allow receive_sender="*"/><allow own="*"/></policy></busconfig>' % tmp)
        cfg = Path(tmp, "config", "booru")
        cfg.mkdir(parents=True)
        (cfg / "state.json").write_text(json.dumps({"blacklist": ["blacklisted_tag"]}))
        for face in ("hypr", "plasma"):
            env = dict(os.environ)
            # A private session bus too: the KDE platform theme segfaults
            # building a menubar offscreen against the live one (coder's
            # ui-test.sh), and nothing here may reach the user's bus anyway.
            for k in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE",
                      "DBUS_SESSION_BUS_ADDRESS"):
                env.pop(k, None)
            env.update(QT_QPA_PLATFORM="offscreen", BOORU_BASE_URL=base, BOORU_DRIVE="1",
                       XDG_CACHE_HOME=str(Path(tmp, "cache")),
                       XDG_CONFIG_HOME=str(Path(tmp, "config")),
                       XDG_RUNTIME_DIR=str(Path(tmp, "run")),
                       XDG_STATE_HOME=str(Path(tmp, "state")),
                       KDESHELL_STATE=str(Path(tmp, "kdeshell.ini")),
                       BOORU_SAVE_DIR=str(Path(tmp, "pictures")))
            Path(tmp, "run").mkdir(exist_ok=True, mode=0o700)
            if shot_dir:
                env["BOORU_SHOT"] = str(shot_dir / f"booru-{face}.png")
                env["BOORU_SHOT_POST"] = "1"
                env["BOORU_SHOT_GRID"] = str(shot_dir / f"booru-{face}-grid.png")
            if face == "plasma":
                env["BOORU_MENUS"] = "1"
            r = subprocess.run(["dbus-run-session", "--config-file=" + str(bus_conf), "--",
                                sys.executable, str(MAIN),
                                "--selftest", "--face=" + face],
                               env=env, capture_output=True, text=True, timeout=120)
            line = next((ln for ln in r.stdout.splitlines() if ln.startswith("BOORU_REPORT ")), "")
            if not line:
                failures.append(f"{face}: no report (exit {r.returncode})\n{r.stderr[-3000:]}")
                continue
            rep = json.loads(line.split(" ", 1)[1])

            def check(name, ok):
                print(("ok   " if ok else "FAIL ") + face + ": " + name)
                if not ok:
                    failures.append(f"{face}: {name}: {json.dumps(rep)[:1500]}")

            check("first page, blacklisted post dropped", rep.get("posts") == 39)
            check("total from counts", rep.get("total") == 80)
            check("second page appended", rep.get("posts_after_more") == 78)
            check("post opens", rep.get("post_open") == 0)
            check("wiki title", rep.get("wiki") == "hatsune_miku")
            check("wiki links are tags", rep.get("wiki_links") == ["vocaloid", "crypton_future_media"])
            check("related tags", rep.get("related") == 2)
            check("prompt spelling", rep.get("prompt", "").startswith("1girl, long hair"))
            check("tag click searches it", rep.get("query_after_tag") == "long_hair")
            check("tag click closes the post", rep.get("post_closed") == -1)
            check("back returns to the earlier search", rep.get("query_after_back") == "hatsune_miku")
            check("history reopens the post", rep.get("post_after_back") == 0)
            # DText reduced to text; a literal tag survives AS TEXT (PixelText
            # is PlainText), never as markup.
            check("wiki dtext reduced", rep.get("wiki_text", "").startswith("About\nA VOCALOID by Crypton. bold"))
            check("completer answers", "hatsune_miku" in rep.get("completions", []))
            check("no QML warnings", not rep.get("warnings"))
            if face == "plasma":
                check("native menus built", "Save Original" in json.dumps(rep.get("chrome", "")))
            if r.returncode not in (0, 1):
                failures.append(f"{face}: exit {r.returncode}\n{r.stderr[-2000:]}")
        leaked = list(Path(tmp, "pictures").glob("*")) if Path(tmp, "pictures").exists() else []
        print(("ok   " if not leaked else "FAIL ") + "nothing saved")
    srv.shutdown()
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
