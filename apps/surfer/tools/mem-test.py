#!/usr/bin/env python3
"""Headless memory measurement for surfer's QtWebEngine render processes —
`apps/surfer/tools/mem-test.py`.

Opens N real WebEngineViews over loopback into one shared persistent profile
(mirroring Main.qml's tab architecture: a Repeater of shared-profile views that
stack so only one is "visible"), then measures the RSS of the WHOLE process tree
(main + every QtWebEngine renderer/GPU/utility descendant read out of /proc, not
just the main python process) and reports what backgrounds tabs pin and what
freezing / discarding them recovers. No screen, no network beyond loopback,
scratch profile dirs — nothing touches the live session.

Usage (see apps/surfer/AGENTS.md — borrow the wrapper's env, never source it):
    surfer-qtenv python3 apps/surfer/tools/mem-test.py [--tabs N] [--discard|--freeze|--none]

  --none (default): repeat measurements with BOTH our discard/freeze pass
                    disabled, to show the baseline (what a hidden tab pins today).
  --discard: run the lifecycle pass that discards all non-visible tabs.
  --freeze : run the lifecycle pass that freezes all non-visible tabs.
  --tabs N : how many tabs to open (default 6; >1 needs N loopback ports).

PSS across the whole process tree is the ownership estimate that matters for
the audit. Summed tree RSS remains beside it because that is what a process
monitor commonly shows, but it double-counts shared pages.

Drives the ENGINE, not a wiring: it sets lifecycleState straight on QML-found
views, so it isolates the memory lever from the Main.qml change that will
eventually apply it. The Main.qml wiring itself is asserted by a separate
drift-guard at the bottom.
"""
import argparse
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESOURCE_SAMPLER = HERE.parents[2] / "tools" / "resource-sampler.py"

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # with no display Qt aborts loudly; it
os.environ.pop("DISPLAY", None)          # cannot fall back onto his session


def _borrow_wrapper_env():
    """Same recipe as find-test.py: read the wrapper's export lines, never run
    it. surfer-qtenv is the sanctioned way, but this must work under the bare
    interpreter the other harnesses re-exec themselves into."""
    wrapper = shutil.which("surfer")
    if not wrapper:
        raise SystemExit("no surfer wrapper to borrow PySide6 and the Qt env from")
    text = Path(os.path.realpath(wrapper)).read_text(errors="replace")
    m = re.search(r'((?:/nix/store/\S+?/bin|/usr/bin)/python3)"?\s+\S*main\.py', text)
    if not m:
        raise SystemExit("could not find main.py's interpreter in %s — if the "
                         "wrapper changed shape, update this harness" % wrapper)
    py = m.group(1)
    if py == "/usr/bin/python3":
        # book's wrapper intentionally uses Fedora's Qt stack directly.  A
        # Nix-shell environment can inject incompatible Qt libraries, so give
        # the system interpreter the same sealed environment used by the
        # offscreen browser harnesses.
        clean_home = tempfile.mkdtemp(prefix="surfer-mem-home-")
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": clean_home,
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "QT_QPA_PLATFORM": "offscreen",
            "_SURFER_MEM_HOME": clean_home,
        }
        fontconfig = re.search(r'export FONTCONFIG_FILE="\$\{FONTCONFIG_FILE:-([^}]+)\}"', text)
        if fontconfig:
            env["FONTCONFIG_FILE"] = fontconfig.group(1)
        return py, env
    qtenv = shutil.which("surfer-qtenv")
    if not qtenv:
        raise SystemExit("no surfer-qtenv wrapper")
    # The environment-only wrapper never runs singleton.py or profile sync.
    out = subprocess.run([qtenv, "env", "-0"],
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
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("DISPLAY", None)
    return py, env


if not os.environ.get("_SURFER_MEM_REEXEC"):
    _py, _env = _borrow_wrapper_env()
    _env["_SURFER_MEM_REEXEC"] = "1"
    os.execve(_py, [_py, str(Path(__file__).resolve())] + sys.argv[1:], _env)

# scratch dirs: nothing this writes lands in the user's profile or caches
scratch = Path(tempfile.mkdtemp(prefix="surfer-mem-"))
atexit.register(shutil.rmtree, scratch, ignore_errors=True)
if os.environ.get("_SURFER_MEM_HOME"):
    atexit.register(shutil.rmtree, os.environ["_SURFER_MEM_HOME"],
                    ignore_errors=True)
for var in ("XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
    d = scratch / var.lower()
    d.mkdir(parents=True, exist_ok=True)
    os.environ[var] = str(d)

from PySide6.QtCore import (QUrl, QTimer, QEventLoop, QObject)  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent  # noqa: E402
from PySide6.QtWebEngineQuick import QtWebEngineQuick  # noqa: E402

QtWebEngineQuick.initialize()
app = QGuiApplication(sys.argv)
if app.platformName() != "offscreen":
    raise SystemExit("refusing to run on platform %r, not offscreen"
                     % app.platformName())


def tree_rss_kb(pid):
    """VmRSS (kB) of pid plus every descendant, read out of /proc."""
    seen = set()
    total = 0

    def walk(p):
        nonlocal total
        if p in seen or not os.path.isdir("/proc/%d" % p):
            return
        seen.add(p)
        try:
            with open("/proc/%d/status" % p) as f:
                for ln in f:
                    if ln.startswith("VmRSS:"):
                        total += int(ln.split()[1])
                        break
        except OSError:
            pass
        try:
            with open("/proc/%d/task/%d/children" % (p, p)) as f:
                children = [int(x) for x in f.read().split()]
        except OSError:
            children = []
        for c in children:
            walk(c)

    walk(pid)
    return total


def rss_mb(pid):
    return tree_rss_kb(pid) / 1024.0


def resource_mb(pid):
    """Tree totals from the repository's canonical smaps_rollup sampler."""
    proc = subprocess.run(
        [sys.executable, str(RESOURCE_SAMPLER), "--pid", str(pid)],
        capture_output=True, text=True, check=True,
    )
    totals = json.loads(proc.stdout)["samples"][0]["totals_memory_kib"]
    return {
        "rss": totals["Rss"] / 1024.0,
        "pss": totals["Pss"] / 1024.0,
        "private": (totals["Private_Clean"] + totals["Private_Dirty"]) / 1024.0,
    }


def renderer_count(pid):
    """Number of QtWebEngine renderer subprocesses in this process tree."""
    import subprocess as sp
    try:
        out = sp.run(["ps", "-o", "pid=,ppid=,args="],
                     capture_output=True, text=True).stdout
    except Exception:
        return -1
    kids = {}
    cmds = {}
    for ln in out.splitlines():
        p = ln.split(None, 2)
        if len(p) < 3:
            continue
        pidv, ppid, args = int(p[0]), int(p[1]), p[2]
        kids.setdefault(ppid, []).append(pidv)
        cmds[pidv] = args
    acc = set()

    def walk(p):
        if p in acc:
            return
        acc.add(p)
        for c in kids.get(p, []):
            walk(c)
    walk(pid)
    return sum(1 for p in acc
               if re.search(r"--type(?:=|\s+)renderer(?:\s|$)", cmds.get(p, "")))


def pump(ms=120):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(pred, ms=20000):
    waited = 0
    while waited < ms and not pred():
        pump(50)
        waited += 50
    return pred()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tabs", type=int, default=6)
    ap.add_argument("--discard", action="store_true")
    ap.add_argument("--freeze", action="store_true")
    args = ap.parse_args()

    n = max(2 if args.discard or args.freeze else 1, args.tabs)
    mode = "discard" if args.discard else ("freeze" if args.freeze else "none")

    # each tab is a DIFFERENT origin (its own loopback port) so it gets its own
    # renderer process — that is what models "many tabs on many sites" and lets
    # us count and sum real renderers rather than one shared one.
    body = ("<html><head><title>mem</title></head><body>"
            "<canvas id='c' width='1600' height='1200'></canvas>"
            "<script>"
            "var ctx=document.getElementById('c').getContext('2d');"
            "for(var i=0;i<400;i++){ctx.fillStyle='#cc4400';"
            "ctx.fillRect(i*4, (i*7)%1200, 200, 200);}"
            "window.__held=new Uint8Array(64*1024*1024);"   # ~64MB pinned per renderer
            "</script></body></html>")

    servers = []
    for port in range(8000, 8000 + n):
        class H(BaseHTTPRequestHandler):
            def do_GET(self_):
                self_.send_response(200)
                self_.send_header("Content-Type", "text/html")
                self_.send_header("Content-Length", str(len(body)))
                self_.end_headers()
                self_.wfile.write(body.encode())

            def log_message(self_, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", port), H)
        servers.append(srv)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    urls = [QUrl("http://127.0.0.1:%d/" % port) for port in range(8000, 8000 + n)]

    engine = QQmlApplicationEngine()
    fixture = QQmlComponent(engine, QUrl.fromLocalFile(str(HERE / "mem-test.qml")))
    if fixture.isError():
        raise SystemExit("the fixture would not compile:\n" + fixture.errorString())
    engine.load(QUrl.fromLocalFile(str(HERE / "mem-test.qml")))
    if not engine.rootObjects():
        raise SystemExit("the fixture would not load")
    root = engine.rootObjects()[0]
    main_pid = os.getpid()

    def resource_report(tag):
        mem = resource_mb(main_pid)
        print("  resource %-18s rss=%8.1f MB  pss=%8.1f MB  private=%8.1f MB"
              % (tag, mem["rss"], mem["pss"], mem["private"]))
        return mem

    # A loaded QML fixture and persistent scratch profile, before navigation.
    # This is the closest safe measure of WebEngine's blank application floor.
    pump(1500)
    resource_report("blank fixture")

    # collect the fixture's views (win0..win5) and load the first `n` of them
    def collect():
        out = []
        for i in range(6):
            v = root.findChild(QObject, "win%d" % i)
            if v is not None:
                out.append(v)
        return out

    views = collect()
    print("trace: %d WebEngineViews found in fixture" % len(views))
    for i, v in enumerate(views[:n]):
        v.setProperty("url", urls[i])
    # wait until every loaded tab reported a successful load
    if not wait_for(lambda: int(root.property("loaded")) >= n, ms=60000):
        got = int(root.property("loaded"))
        print("WARN: only %d/%d tabs loaded (views=%d); measuring anyway"
              % (got, n, len(views)))

    # give page-side JS (the canvas + 64MB alloc) a moment to settle
    pump(1500)

    base_mb = rss_mb(main_pid)

    # probe QtWebEngine's lifecycleState property + enum values
    try:
        mo = views[0].metaObject()
        idx = mo.indexOfProperty("lifecycleState")
        if idx >= 0:
            prop = mo.property(idx)
            print("trace: lifecycleState property index = %d, enum: 0=%s 1=%s 2=%s"
                  % (idx, prop.enumerator().valueToKey(0),
                     prop.enumerator().valueToKey(1),
                     prop.enumerator().valueToKey(2)))
        else:
            print("trace: WebEngineView has no lifecycleState property")
    except Exception as e:
        print("trace: lifecycleState probe failed (%r)" % e)

    def report(tag):
        cur = rss_mb(main_pid)
        print("  %-26s tree_rss = %8.1f MB  (%+8.1f vs baseline), %2d renderers"
              % (tag, cur, cur - base_mb, renderer_count(main_pid)))
        return cur

    print("== mode: %s, %d tabs loaded ==" % (mode, n))
    report("all loaded, only 0 on screen")
    resource_report("tabs loaded")

    # how many child (renderer/gpu/utility) processes exist now?
    kids = []
    try:
        with open("/proc/%d/task/%d/children" % (main_pid, main_pid)) as f:
            kids = [int(x) for x in f.read().split()]
    except OSError:
        pass
    print("  trace: %d direct children (renderer/gpu/utility procs)" % len(kids))

    # ---- the lifecycle pass: act on every hidden tab (1..n-1) ----
    if mode != "none":
        for i, v in enumerate(views[:n]):
            if i == 0:
                continue
            try:
                if mode == "discard":
                    v.setProperty("lifecycleState", 2)   # LifecycleState.Discarded
                else:
                    v.setProperty("lifecycleState", 1)   # LifecycleState.Frozen
            except Exception as e:
                print("  trace: set lifecycleState[%d] failed: %r" % (i, e))
        pump(3000)
        report("after %s of the %d hidden tabs" % (mode, n - 1))
        resource_report("after " + mode)
    else:
        # baseline mode: never discard — shows what hidden tabs pin
        pump(3000)
        report("background tabs hidden (never discarded)")

    # ---- drift-guard: Main.qml must still apply the same lifecycle logic ----
    MAIN_QML = (HERE.parent / "qml" / "Main.qml").read_text(encoding="utf-8")
    needed = ["discardIdleTabs", "discardAfter", "LifecycleState.Discarded",
              "LifecycleState.Active", "lastSeen", "onPaneChanged"]
    missing = [tok for tok in needed if tok not in MAIN_QML]
    print("  trace: Main.qml memory-saver wiring present: %s"
          % ("YES" if not missing else ("MISSING " + ",".join(missing))))
    # and the profile on the Python side still caps the disk cache
    MAIN_PY = (HERE.parent / "main.py").read_text(encoding="utf-8")
    print("  trace: main.py caps the disk cache: %s"
          % ("setHttpCacheMaximumSize" in MAIN_PY))

    for srv in servers:
        srv.shutdown()
    # Delete the fixture and let WebEngine reap its renderer processes.  This
    # measures teardown residue without touching the persistent user profile.
    root.deleteLater()
    pump(5000)
    resource_report("fixture cleanup")
    app.exit(0)


if __name__ == "__main__":
    main()
