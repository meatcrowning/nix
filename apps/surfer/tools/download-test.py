#!/usr/bin/env python3
"""Headless reproduction of surfer's download-progress toast — `--old`/default.

Why this exists: a real download of a slow *small* image showed no in-place
PROGRESS toast (docs/DESIGN.md 10.4), only the completion toast. The progress
gate lived in QML and was keyed on SIZE alone (`totalBytes > 3145728`, > 3 MB);
a small file on a slow connection never qualified, so `Downloads.progress` was
never called even though the download took long enough that the user was left
waiting on a silent screen. DESIGN 10.4's principle is about a download that
takes TIME ("longer downloads ... stay on the screen until they are finished"),
so the gate must be duration-aware, not size-only.

It drives a REAL offscreen QtWebEngine download of a small file served slowly
over loopback (never a real toast, never his screen, never his profile — the
profile here is off-the-record). Two wiring modes:

  --old   wire the OLD size-only QML gate; assert progress never fires for a
          small slow download (this is the reproduction).
  (default/new)  wire the bridge-decides path; assert the SAME small slow
          download now emits a live progress toast and morphs it in place.

Run it after touching `Downloads` in main.py or the download block in Main.qml.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent

BIG = 3 * 1024 * 1024   # must match the size trigger in Downloads (3 MB)

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session
os.environ.pop("DISPLAY", None)


# ---- borrow the packaged wrapper's env, exactly as find-test.py does ---------
def _borrow_wrapper_env():
    wrapper = shutil.which("surfer")
    if not wrapper:
        raise SystemExit("no surfer wrapper to borrow PySide6 and the Qt env from")
    text = Path(os.path.realpath(wrapper)).read_text(errors="replace")
    m = re.search(r'(/nix/store/\S+?/bin/python3)"?\s+\S*main\.py', text)
    if not m:
        raise SystemExit("could not find main.py's interpreter in %s" % wrapper)
    py = m.group(1)
    body = "\n".join(ln for ln in text.splitlines()
                     if not ln.startswith("#!")
                     and "singleton.py" not in ln
                     and not ln.startswith("exec "))
    out = subprocess.run(["bash", "-c", body + "\nexec env -0\n"],
                         capture_output=True, check=True).stdout
    env = dict(os.environ)
    for entry in out.split(b"\0"):
        if not entry or b"=" not in entry:
            continue
        k, v = entry.decode(errors="replace").split("=", 1)
        if k in ("HOME", "PWD", "SHLVL", "_",
                 "QT_QPA_PLATFORM", "WAYLAND_DISPLAY", "DISPLAY"):
            continue
        env[k] = v
    return py, env


if not os.environ.get("_SURFER_DL_REEXEC") and not os.environ.get("SURFER_QTSHELL"):
    _py, _env = _borrow_wrapper_env()
    _env["_SURFER_DL_REEXEC"] = "1"
    os.execve(_py, [_py, str(Path(__file__).resolve())] + sys.argv[1:], _env)

# scratch: nothing here touches the user's dirs or his running browser
scratch = Path(tempfile.mkdtemp(prefix="surfer-dl-"))
for var in ("XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
    d = scratch / var.lower()
    d.mkdir(parents=True, exist_ok=True)
    os.environ[var] = str(d)
dl_home = scratch / "Downloads"
dl_home.mkdir(parents=True, exist_ok=True)
os.environ["HOME"] = str(scratch)

sys.path.insert(0, str(HERE.parent))          # surfer's main.py
from PySide6.QtCore import QUrl, QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication                                       # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage          # noqa: E402
from PySide6.QtWebEngineQuick import QtWebEngineQuick                           # noqa: E402

import main as surfer                          # noqa: E402  (main() is guarded)


# ---- a small file served slowly, a modest HTML page ---------------------------
FILE_BYTES = 320 * 1024        # 320 KB — well under the 3 MB gate
CHUNK = 4 * 1024               # 4 KB per send
CHUNK_PAUSE = 0.12             # 120 ms — ~9.6 s to stream the whole file


class SlowHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/file.bin":
            self.send_response(200)
            self.send_header("Content-Length", str(FILE_BYTES))
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            sent = 0
            while sent < FILE_BYTES:
                n = min(CHUNK, FILE_BYTES - sent)
                self.wfile.write(b"\0" * n)
                self.wfile.flush()
                sent += n
                time.sleep(CHUNK_PAUSE)
        elif self.path == "/page.html":
            body = b"<html><body><a id=l href='/file.bin' download>dl</a></body></html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()


# ---- a spy over the real Downloads bridge: count toast emissions -------------
class SpyDownloads(surfer.Downloads):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sends = []      # (kind, title, body)
        self.last_id = 1

    def _send(self, key, title, body, value, persist=False, path=None):
        # do NOT shell out to notify-send (no daemon offscreen, and never a real
        # toast anyway) — record what WOULD be sent, including the -r replace id
        # and the download image path hint.
        rid = self._ids.get(key)
        assigned = self.last_id
        self.sends.append({
            "key": key, "title": title, "rid": rid,
            "persist": persist, "value": value, "assigned": assigned,
            "path": path,
        })
        self._ids[key] = assigned
        self.last_id += 1


dl = SpyDownloads()


def wire_download(profile, mode):
    """Replicate Main.qml's onDownloadRequested wiring. mode 'old' = the size-only
    gate as it shipped (reproduction); otherwise the bridge-decides path."""
    state = {"seq": 0}

    def on_download_requested(download):
        download.setDownloadDirectory(str(dl_home))
        download.accept()
        key = "dl" + str(state["seq"])
        state["seq"] += 1
        name = download.downloadFileName()
        started = time.monotonic()

        def on_received():
            if download.isFinished():
                return
            if mode == "old":
                if download.totalBytes() > BIG:
                    dl.progress(key, name, download.receivedBytes(),
                                download.totalBytes())
            else:
                # bridge owns the size/time decision (new path)
                dl.progress(key, name, download.receivedBytes(),
                            download.totalBytes(),
                            (time.monotonic() - started) * 1000.0)

        def on_finished():
            if not download.isFinished():
                return
            from PySide6.QtWebEngineCore import QWebEngineDownloadRequest
            if download.state() == QWebEngineDownloadRequest.DownloadCompleted:
                dl.done(key, name)
            else:
                dl.failed(key, name)

        download.receivedBytesChanged.connect(on_received)
        download.isFinishedChanged.connect(on_finished)

    profile.downloadRequested.connect(on_download_requested)
    return profile.downloadRequested  # keep connection alive


def pump(ms=60):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def run_once(mode, timeout_s=30):
    dl.sends.clear()
    dl._ids.clear()
    dl._pct.clear()
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    QtWebEngineQuick.initialize()
    # a unique storage name under the scratch XDG dirs: cannot contend for the
    # user's running persistent "surfer" profile (separate dir, separate name)
    profile = QWebEngineProfile("dl-test-" + mode, app)
    wire_download(profile, mode)
    page = QWebEnginePage(profile, app)
    page.load(QUrl("http://127.0.0.1:%d/page.html" % port))
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and page.url().path() != "/page.html":
        pump()
    # trigger the download directly
    page.download(QUrl("http://127.0.0.1:%d/file.bin" % port), "file.bin")
    # wait for the download to finish (streaming + a little)
    waited = 0
    while waited < timeout_s * 1000 and not dl.finished_seen and \
            not [s for s in dl.sends if s["title"].startswith("download ")]:
        pump(120)
        waited += 120
        time.sleep(0)
    # let any trailing signals land
    for _ in range(10):
        pump(120)
    return dl


dl.finished_seen = False


def _expect(label, sends, count, persist=None):
    ok = len(sends) == count and (persist is None or all(
        s["persist"] is persist for s in sends))
    print(("  ok   " if ok else "  FAIL ") + "%-46s %d" % (label, len(sends))
          + ("" if ok else " (want %d%s)" %
             (count, "" if persist is None else ", persist=%r" % persist)))
    return ok


def main():
    mode = "new"
    if "--old" in sys.argv:
        mode = "old"
    print("== surfer download-progress bridge test (%s wiring) ==" % mode,
          flush=True)
    print("file=%dKB < %dMB gate" % (FILE_BYTES // 1024, BIG // (1024 * 1024)),
          flush=True)
    dl_state = run_once(mode)

    progress = [s for s in dl_state.sends if s["title"].startswith("downloading ")]
    completes = [s for s in dl_state.sends if s["title"].startswith("download ")]

    print("progress toasts emitted: %d" % len(progress))
    if mode == "old":
        if len(progress) == 0 and len(completes) >= 1:
            print("REPRODUCED: a slow %d KB download produced NO progress toast, "
                  "only a completion toast" % (FILE_BYTES // 1024))
            return 0
        print("unexpected: old wiring produced progress toasts — gate changed?")
        return 1

    # new path
    if len(progress) == 0:
        print("FAIL: bridge emitted no progress toast for a slow small download")
        return 1
    first = progress[0]
    if first["persist"] is not True:
        print("FAIL: progress toast not persistent (-t 0): %r" % first)
        return 1
    # in-place morph: every later update carries the id the previous one got
    chain_ok = all(progress[i]["rid"] == progress[i - 1]["assigned"]
                   for i in range(1, len(progress)))
    if chain_ok:
        print("ok   : %d updates replaced in place (single toast morphed)"
              % len(progress))
    else:
        print("FAIL: updates did not replace in place: %r" % progress)
        return 1

    print("\n-- decision gate (the real Downloads bridge) --")
    dl.sends.clear()
    dl._ids.clear()
    dl._pct.clear()
    ok = True

    # fast + small: no progress toast (would only flash) — only completion
    dl.progress("k-fast", "f.png", 50_000, 200_000, 100.0)
    ok &= _expect("fast small -> no toast", dl.sends, 0)

    # slow + small: a toast, persisted, in place
    dl.progress("k-slow", "f.png", 50_000, 200_000, 2000.0)
    ok &= _expect("slow small -> progress toast", dl.sends, 1)
    ok &= _expect("  ... persistent (-t 0)", dl.sends, 1, persist=True)
    dl.progress("k-slow", "f.png", 110_000, 200_000, 2100.0)
    ok &= _expect("  ... next percent replaces in place",
                  [s for s in dl.sends if s["key"] == "k-slow"], 2)
    ok &= dl.sends[-1]["rid"] == dl.sends[-2]["assigned"]

    # same whole-percent value again: throttled, no resend
    before = len(dl.sends)
    dl.progress("k-slow", "f.png", 111_000, 200_000, 2200.0)  # still 55%
    ok &= _expect("  ... same percent throttled", dl.sends, before)

    # large + fast: toasts on size alone
    dl.progress("k-big", "b.bin", 5_000_000, 10_000_000, 80.0)
    ok &= _expect("large fast -> progress toast (size trigger)", dl.sends, before + 1)

    # no denominator: never toasts, and does not latch a throttle
    dl.progress("k-unk", "u.bin", 100, -1, 5000.0)
    ok &= _expect("unknown total -> no toast", dl.sends, before + 1)

    # an image completion toast carries the downloaded image's path (the panel
    # thumbnails + opens it); a non-image completion carries no path
    dl._ids.clear(); dl._pct.clear()
    start = len(dl.sends)
    dl.done("k-img", "pic.png", "/home/lam/Downloads/pic.png")
    dl.done("k-pdf", "doc.pdf", "/home/lam/Downloads/doc.pdf")
    ok &= _expect("done x2 -> two completion toasts", dl.sends, start + 2)
    ok &= dl.sends[-2]["path"] == "/home/lam/Downloads/pic.png"
    ok &= dl.sends[-1]["path"] is None
    print(("  ok   " if dl.sends[-2]["path"] else "  FAIL ")
          + "image done threads the path for the panel")
    print(("  ok   " if dl.sends[-1]["path"] is None else "  FAIL ")
          + "non-image done carries no image path")

    print("\n-- Main.qml wiring (must not drift from the bridge) --")
    main_qml = (HERE.parent / "qml" / "Main.qml").read_text(encoding="utf-8")
    wiring_ok = True
    checks = [
        ("calls Downloads.progress with elapsed time",
         r"Downloads\.progress\(key, name, download\.receivedBytes,\s*\n\s*download\.totalBytes, Date\.now\(\) - started\)"),
        ("sets downloadDirectory and accepts",
         r"download\.downloadDirectory = downloadDir;"),
        ("done/failed on finish",
         "Downloads.done(key, name, path);" in main_qml and
         "Downloads.failed(key, name);" in main_qml),
    ]
    for label, pat in checks:
        found = bool(re.search(pat, main_qml)) if isinstance(pat, str) else pat
        wiring_ok &= found
        print(("  ok   " if found else "  FAIL ") + label)
    if not wiring_ok:
        return 1

    print("\n" + ("ok   : download-progress bridge test PASSED"
                  if ok else "FAIL : see above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
