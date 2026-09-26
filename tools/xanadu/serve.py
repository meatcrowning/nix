#!/usr/bin/env python3
"""Serve the Xanadu page with a live editor over this repo's working tree.

  tools/xanadu/serve.py [--port 8787] [--open]

Binds 127.0.0.1 only. Every request must carry the loopback Host header and
every API call the per-run token embedded in the page, so no other site or
rebinding trick can reach the write path.

Saves are all-or-nothing: each file's on-disk hash must still match what the
page loaded (other agents edit this tree), every .nix file must parse, then
all files are written atomically. Renames move the file and `git add -N` the
new path; nothing is committed or staged beyond intent-to-add.
"""
import argparse
import hashlib
import http.server
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build  # noqa: E402

TOKEN = secrets.token_urlsafe(24)
FORBIDDEN_TOP = {".git", "docs", "sounds"}
IN_FILE = re.compile(r"/nix/store/[a-z0-9]{32}-source/([^:\s'`]+\.nix)'")
ERR_AT = re.compile(r"at (?:/nix/store/[a-z0-9]{32}-source/|(?P<abs>/[^:\s]+?/))(?P<path>[^:\s«»]+):(?P<line>\d+):(?P<col>\d+)")


def sha(b):
    return hashlib.sha256(b).hexdigest()


def safe_rel(path):
    """A repo-relative page path we are willing to create or write."""
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        return None
    norm = os.path.normpath(path)
    if norm != path or norm.startswith("..") or norm.split("/")[0] in FORBIDDEN_TOP:
        return None
    if not (norm.endswith(".nix") or norm in build.GUIDES):
        return None
    return norm


def parse_nix(text):
    """None if it parses, else {line, col, msg} from nix-instantiate --parse."""
    with tempfile.NamedTemporaryFile("w", suffix=".nix", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        tmp = fh.name
    try:
        r = subprocess.run(["nix-instantiate", "--parse", tmp], capture_output=True, text=True, timeout=30)
    finally:
        os.unlink(tmp)
    if r.returncode == 0:
        return None
    err = r.stderr
    m = re.search(re.escape(tmp) + r":(\d+):(\d+)", err)
    msg = next((l.strip()[len("error:"):].strip() for l in err.splitlines() if l.strip().startswith("error:")), err.strip()[:300])
    return {"line": int(m.group(1)) if m else 1, "col": int(m.group(2)) if m else 1, "msg": msg}


class Checker:
    """One background flake evaluation at a time; errors mapped back to repo paths."""

    def __init__(self, root):
        self.root, self.lock, self.job = root, threading.Lock(), None

    def attr(self):
        host = ""
        probe = os.path.expanduser("~/.config/scripts/claude-host-id.sh")
        if os.access(probe, os.X_OK):
            host = subprocess.run([probe], capture_output=True, text=True).stdout
        host = host or socket.gethostname()
        if re.search(r"\btop\b", host):
            return ".#nixosConfigurations.top.config.system.build.toplevel.drvPath"
        return ".#homeConfigurations.air.activationPackage.drvPath"

    def start(self):
        with self.lock:
            if self.job and self.job["state"] == "running":
                return self.job
            self.job = {"id": secrets.token_hex(6), "state": "running", "started": time.time(),
                        "attr": self.attr(), "ok": None, "errors": [], "tail": ""}
            threading.Thread(target=self.run, args=(self.job,), daemon=True).start()
            return self.job

    def run(self, job):
        cmd = [os.path.join(self.root, "tools/nix-private.sh"), "eval", "--raw", job["attr"]]
        try:
            r = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True, timeout=900)
            out, ok = r.stderr, r.returncode == 0
        except subprocess.TimeoutExpired:
            out, ok = "evaluation timed out after 900s", False
        errors, seen = [], set()
        # nix opens with a bare "error:" and states the cause in the last one
        msgs = [l.strip()[len("error:"):].strip() for l in out.splitlines() if l.strip().startswith("error:")]
        msg = next((m for m in reversed(msgs) if m), "")
        # module errors often name only the file ("In `/nix/store/…-source/x.nix'")
        spots = [m.groupdict() for m in ERR_AT.finditer(out)] or [
            {"path": m.group(1), "line": "1", "col": "1", "abs": None} for m in IN_FILE.finditer(out)]
        for d in spots:
            path = d["path"]
            if d["abs"]:
                if not (d["abs"] + path).startswith(self.root + "/"):
                    continue
                path = os.path.relpath(d["abs"] + path, self.root)
            key = (path, d["line"])
            if path and key not in seen and os.path.isfile(os.path.join(self.root, path)):
                seen.add(key)
                errors.append({"path": path, "line": int(d["line"]), "col": int(d["col"]), "msg": msg})
        job.update(state="done", ok=ok, errors=errors if not ok else [],
                   tail="\n".join(out.strip().splitlines()[-40:]), took=round(time.time() - job["started"], 1))


def make_handler(root, inject, checker, port):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def guard(self, api):
            if self.headers.get("Host") not in hosts:
                self.reply(403, {"error": "bad host"})
                return False
            if api and self.headers.get("X-Xanadu-Token") != TOKEN:
                self.reply(403, {"error": "bad token"})
                return False
            return True

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if not self.guard(u.path.startswith("/api/")):
                return
            if u.path == "/":
                html = build.render(build.page_data(root), {"token": TOKEN})
                if inject:
                    with open(inject, encoding="utf-8") as fh:
                        html += "\n<script>\n" + fh.read() + "\n</script>\n"
                return self.reply(200, html.encode(), "text/html; charset=utf-8")
            if u.path == "/api/file":
                path = urllib.parse.parse_qs(u.query).get("path", [""])[0]
                if path not in build.tracked(root):
                    return self.reply(404, {"error": "not a page"})
                return self.reply(200, build.page_of(root, path))
            if u.path == "/api/check":
                return self.reply(200, checker.job or {"state": "idle"})
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            if not self.guard(True):
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            except ValueError:
                return self.reply(400, {"error": "bad json"})
            if u.path == "/api/save":
                code, out = save(root, body.get("files", []))
                return self.reply(code, out)
            if u.path == "/api/check":
                return self.reply(200, checker.start())
            self.reply(404, {"error": "not found"})

    return H


def save(root, files):
    if not files:
        return 200, {"hashes": {}}
    tracked = set(build.tracked(root))
    plan, conflicts, errors, bad = [], [], [], []
    for f in files:
        dst, src = safe_rel(f.get("path")), f.get("from") or f.get("path")
        if not dst or src not in tracked or not isinstance(f.get("text"), str):
            bad.append(f.get("path"))
            continue
        if src != dst and (dst in tracked or os.path.exists(os.path.join(root, dst))):
            bad.append(dst)
            continue
        with open(os.path.join(root, src), "rb") as fh:
            if sha(fh.read()) != f.get("base"):
                conflicts.append(src)
        plan.append((src, dst, f["text"]))
    if bad:
        return 400, {"error": "refused paths", "paths": bad}
    if conflicts:
        return 409, {"error": "changed on disk", "conflicts": conflicts}
    for src, dst, text in plan:
        if dst.endswith(".nix"):
            e = parse_nix(text)
            if e:
                errors.append({"path": dst, **e})
    if errors:
        return 422, {"error": "parse", "errors": errors}
    staged = []
    for src, dst, text in plan:
        target = os.path.join(root, dst)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".xanadu-tmp"
        with open(tmp, "wb") as fh:
            fh.write(text.encode("utf-8"))
        os.chmod(tmp, os.stat(os.path.join(root, src)).st_mode & 0o7777)
        staged.append((tmp, target, src, dst))
    hashes = {}
    for tmp, target, src, dst in staged:
        os.replace(tmp, target)
        if src != dst:
            os.remove(os.path.join(root, src))
            subprocess.run(["git", "-C", root, "add", "-N", "--", dst], check=False)
        with open(target, "rb") as fh:
            hashes[dst] = sha(fh.read())
    return 200, {"hashes": hashes}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--root", default=build.ROOT, help="repo to serve (tests point this at a scratch clone)")
    ap.add_argument("--inject", help="append this script to the page (test harnesses)")
    ap.add_argument("--open", action="store_true", help="open the page with xdg-open")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(root, a.inject, Checker(root), a.port))
    url = f"http://127.0.0.1:{a.port}/"
    print(f"xanadu editor on {url} (root {root}); Ctrl+C stops it", flush=True)
    if a.open:
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
