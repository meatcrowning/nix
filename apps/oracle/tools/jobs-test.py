#!/usr/bin/env python3
"""Background jobs: the runner, the four tools, and the tray in BOTH faces.

Offscreen, against a STUB ollama and a THROWAWAY jobs root — his own jobs
directory is never read or written, his daemon is never touched, and nothing
reaches his screen. The jobs it starts are `sleep`/`echo` in that temp root.

What it covers:

  * `tools/job-run.py` — start, list, tail, stop, clear; a job outliving the
    process that started it; a killed runner not being reported as running
  * the model's four tools (`run_job`, `job_status`, `job_log`, `job_stop`)
    through the real dispatcher
  * the tray renders in the HYPRLAND face and in the PLASMA face, each with its
    own component (`JobRow.qml` / `+plasma/JobRow.qml`), and reports the state,
    the label and the elapsed clock in both
"""
import http.server
import json
import re
import subprocess
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

TMP = tempfile.mkdtemp(prefix="chatter-jobs-test-")
os.environ["ORACLE_JOBS"] = os.path.join(TMP, "jobs")


class Stub(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"models": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.do_GET()

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["OLLAMA_HOST"] = "http://127.0.0.1:%d" % srv.server_address[1]

from PySide6.QtCore import QTimer, QUrl                 # noqa: E402
from PySide6.QtGui import QGuiApplication               # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent   # noqa: E402

sys.argv = [sys.argv[0], "--selftest"]
import main as oracle                                   # noqa: E402
import kdeshell                                         # noqa: E402

app = QGuiApplication([])
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


def pump(until, ms=15000):
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(app.quit)
    t.start(ms)
    poll = QTimer()
    poll.timeout.connect(lambda: until() and app.quit())
    poll.start(50)
    app.exec()
    poll.stop()
    t.stop()


jobs = oracle.Jobs()
ol = oracle.Ollama()
ol._jobs = jobs

# ---- the runner ------------------------------------------------------------
out = jobs.start("echo one; echo two; sleep 2; echo three", label="counter")
check("starting a job answers with an id at once", bool(out.get("id")), str(out))
job_id = out.get("id", "")
check("and it is running, not blocking this process",
      jobs.status(job_id)["jobs"][0]["state"] in ("starting", "running"),
      json.dumps(jobs.status(job_id))[:140])

pump(lambda: jobs.status(job_id)["jobs"][0]["tail"], 8000)
snap = jobs.status(job_id)["jobs"][0]
check("its output is readable WHILE it runs", "one" in snap["tail"],
      str(snap["tail"]))
check("the clock is running", snap["seconds"] > 0, str(snap["seconds"]))

pump(lambda: jobs.status(job_id)["jobs"][0]["state"] == "done", 15000)
snap = jobs.status(job_id)["jobs"][0]
check("it finishes, with the exit code", snap["state"] == "done"
      and snap["exit"] == 0, json.dumps(snap)[:120])
check("and the whole log is there", snap["tail"][-1] == "three",
      str(snap["tail"]))

# a failure is a failure, not a silent "done"
bad = jobs.start("echo nope >&2; exit 3", label="fails")
pump(lambda: jobs.status(bad["id"])["jobs"][0]["state"] == "failed", 15000)
snap = jobs.status(bad["id"])["jobs"][0]
check("a non-zero exit is FAILED, with the code",
      snap["state"] == "failed" and snap["exit"] == 3, json.dumps(snap)[:120])
check("and stderr is in the log too", "nope" in snap["tail"], str(snap["tail"]))

# stop takes the whole process group down
slow = jobs.start("sleep 120", label="sleeper")
pump(lambda: jobs.status(slow["id"])["jobs"][0]["state"] == "running", 8000)
jobs.stop(slow["id"])
pump(lambda: jobs.status(slow["id"])["jobs"][0]["state"] == "stopped", 15000)
check("stop stops it", jobs.status(slow["id"])["jobs"][0]["state"] == "stopped")

# a runner killed outright must not be reported as running for ever
orphan = jobs.start("sleep 120", label="orphan")
pump(lambda: jobs.status(orphan["id"])["jobs"][0]["state"] == "running", 8000)
d = os.path.join(os.environ["ORACLE_JOBS"], orphan["id"])
status = json.load(open(os.path.join(d, "status.json")))
os.system("kill -9 %d 2>/dev/null" % status["pid"])
time.sleep(0.4)
check("a job whose runner died reads as failed, not running",
      jobs.status(orphan["id"])["jobs"][0]["state"] == "failed",
      json.dumps(jobs.status(orphan["id"]))[:140])

# clear only takes the finished ones
keep = jobs.start("sleep 60", label="keeper")
pump(lambda: jobs.status(keep["id"])["jobs"][0]["state"] == "running", 8000)
jobs.clear()
left = [j["id"] for j in jobs.status()["jobs"]]
check("clear leaves the RUNNING job alone", left == [keep["id"]], str(left))
jobs.stop(keep["id"])

# ---- the four tools --------------------------------------------------------
sink = {"sink": [None], "n": 1, "done": None}
ol._run_job_tool("run_job", {"command": "echo hello", "label": "tool job"},
                 0, sink, [])
res = json.loads(sink["sink"][0]["content"])
check("run_job hands the model an id", bool(res.get("id")), json.dumps(res)[:120])
tool_id = res["id"]
pump(lambda: jobs.status(tool_id)["jobs"][0]["state"] == "done", 15000)

sink = {"sink": [None], "n": 1, "done": None}
ol._run_job_tool("job_status", {"id": tool_id}, 0, sink, [])
res = json.loads(sink["sink"][0]["content"])
check("job_status reports it", res["jobs"][0]["state"] == "done",
      json.dumps(res)[:120])

sink = {"sink": [None], "n": 1, "done": None}
ol._run_job_tool("job_log", {"id": tool_id, "lines": 5}, 0, sink, [])
res = json.loads(sink["sink"][0]["content"])
check("job_log reads the output", "hello" in res["jobs"][0]["tail"],
      json.dumps(res)[:120])

check("run_job is offered on EVERY turn", "run_job" in oracle.CORE_TOOL_NAMES)
note = oracle.tools_note()
check("and the other three are in the index",
      all(("- " + n + " ") in note for n in
          ("job_status", "job_log", "job_stop")))

# ---- the tray, in both faces ----------------------------------------------
# Two jobs written straight into a THROWAWAY jobs root — one running, one
# finished — so the tray has something to draw without a single process of his
# being started. The "running" one is pinned to this harness's own pid, which is
# what `job-run.py` checks a running job against.
jobs.clear()
# A ROOT OF ITS OWN for the window runs: a job still stopping from the section
# above would otherwise turn up in the tray and make the count flaky.
os.environ["ORACLE_JOBS"] = os.path.join(TMP, "tray-jobs")
os.makedirs(os.environ["ORACLE_JOBS"], exist_ok=True)
for job_id, state, label, extra in (
        ("100-scan", "running", "library scan", {"pid": os.getpid()}),
        ("101-tags", "done", "tag sweep", {"exit": 0, "ended": time.time()})):
    d = os.path.join(os.environ["ORACLE_JOBS"], job_id)
    os.makedirs(d, exist_ok=True)
    json.dump({"id": job_id, "label": label, "command": "true",
               "lang": "bash", "cwd": TMP, "max_seconds": 60},
              open(os.path.join(d, "spec.json"), "w"))
    status = {"state": state, "started": time.time() - 90}
    status.update(extra)
    json.dump(status, open(os.path.join(d, "status.json"), "w"))
    open(os.path.join(d, "log"), "w").write("scanning\nstill scanning\n")


def selftest(face):
    """One offscreen run of the real window in `face`, as its printed lines —
    the same shape tools/continue-button-test.py uses, because a QML tree built
    by hand in-process is not the tree he actually gets."""
    env = dict(os.environ)
    env["ORACLE_FAKE"] = "1"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("DISPLAY", None)
    if face == "plasma":
        env["XDG_CURRENT_DESKTOP"] = "KDE"
        env["QT_QPA_PLATFORMTHEME"] = "kde"
        env["DESK_SESSION"] = "plasma"
    else:
        env["XDG_CURRENT_DESKTOP"] = "Hyprland"
        env.pop("QT_QPA_PLATFORMTHEME", None)
        env.pop("DESK_SESSION", None)
    out = subprocess.run([sys.executable, str(APP / "main.py"), "--selftest"],
                         env=env, capture_output=True, text=True, timeout=240)
    return out.stdout + out.stderr


for face in ("hypr", "plasma"):
    txt = selftest(face)
    tray = re.search(r"jobs tray: face=(\S+) visible=(\S+) height=(\d+) rows=(\d+)",
                     txt)
    rows = re.findall(r"jobs row: face=(\S+) state=(\S+) label='([^']*)' verbs=(\d+)",
                      txt)
    right = re.search(r"jobs status right: '([^']*)'", txt)
    check("%s: the tray is drawn by its own component" % face,
          tray is not None and tray.group(1) == face,
          tray.group(0) if tray else txt[-400:])
    check("%s: it is visible, with height to draw in" % face,
          tray is not None and tray.group(2) == "True"
          and int(tray.group(3)) > 20, tray.group(0) if tray else "")
    check("%s: one row per job" % face,
          tray is not None and int(tray.group(4)) == 2,
          tray.group(0) if tray else "")
    check("%s: every row is that face's twin" % face,
          len(rows) == 2 and all(r[0] == face for r in rows), str(rows))
    check("%s: the running job says so, by name" % face,
          any(r[1] == "running" and r[2] == "library scan" for r in rows),
          str(rows))
    check("%s: the finished one says done" % face,
          any(r[1] == "done" and r[2] == "tag sweep" for r in rows), str(rows))
    # A running row offers log + stop; a finished one offers log + clear. Both
    # are two — the verb that does not apply is not drawn (docs/DESIGN.md §10.2).
    check("%s: each row offers exactly its two verbs" % face,
          all(int(r[3]) == 2 for r in rows), str(rows))
    check("%s: the status bar carries the count" % face,
          right is not None and right.group(1).startswith("1 job · "),
          right.group(0) if right else txt[-300:])
    check("%s: and the window still loads clean" % face,
          "0 QML warning(s)" in txt, txt[-300:])

srv.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
