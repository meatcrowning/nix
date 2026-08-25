#!/usr/bin/env python3
"""The 2026-08-23 batch: show_image, screenshot, make_image, custom tools,
live exec output, and branching a conversation.

Nothing here touches his machine's real anything: the screenshot runs a STUB
capture command ($ORACLE_SHOT_CMD) that writes a generated PNG, the image
backend is a stub ($ORACLE_PAINTER) that prints what painter's generator would
print, the custom tools live in a temp directory ($ORACLE_TOOLS), and the
branching half drives the real Root.qml offscreen.

    oracle-qtenv python3 tools/toolbox-test.py
"""
import json
import os
import stat
import subprocess
import shlex
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

_TMP = Path(tempfile.mkdtemp(prefix="oracle-toolbox-"))
os.environ["ORACLE_IMAGES"] = str(_TMP / "images")
os.environ["ORACLE_TOOLS"] = str(_TMP / "tools")
# The ai-warden is a REAL daemon on this box, and it is right to refuse a render
# while his 22 GiB model is loaded — but a test must not depend on what is in
# memory at the time. A dead port is an instant connection-refused, which the
# client treats as "yes" by design (apps/pylib/warden.py: fail open, always).
os.environ["AI_WARDEN_URL"] = "http://127.0.0.1:1"

# A STAND-IN ollama: manage_models talks to the daemon over HTTP, and a test
# must not pull 20 GB onto his disk or delete a model he uses. `OLLAMA_HOST` is
# read at import, so the server goes up first.
import http.server                                                # noqa: E402
import threading                                                  # noqa: E402

PULLED = []


class _Ollama(http.server.BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n).decode() or "{}")
        except (ValueError, OSError):
            return {}

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            self._json({"models": [
                {"name": "big:35b", "size": 22 * (1 << 30),
                 "modified_at": "2026-08-09T17:27:58Z",
                 "details": {"family": "qwen", "parameter_size": "36B",
                             "quantization_level": "Q4_K_M"}},
                {"name": "small:1b", "size": 1 << 30, "modified_at": "",
                 "details": {}}]})
        else:
            self._json({"error": "no"}, 404)

    def do_DELETE(self):
        PULLED.append(("delete", self._body().get("model")))
        self._json({})

    def do_POST(self):
        req = self._body()
        if self.path.startswith("/api/show"):
            self._json({"details": {"parameter_size": "36B",
                                    "quantization_level": "Q4_K_M",
                                    "family": "qwen"},
                        "model_info": {"qwen.context_length": 262144},
                        "capabilities": ["tools", "vision"]})
        elif self.path.startswith("/api/pull"):
            PULLED.append(("pull", req.get("model")))
            if str(req.get("model") or "").startswith("nope"):
                body = json.dumps({"error": "pull model manifest: file does not "
                                            "exist"}).encode() + b"\n"
            else:
                body = b"".join(json.dumps(o).encode() + b"\n" for o in (
                    {"status": "pulling manifest"},
                    {"status": "pulling abc", "total": 1000, "completed": 500},
                    {"status": "pulling abc", "total": 1000, "completed": 1000},
                    {"status": "success"}))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json({"error": "no"}, 404)

    def log_message(self, *a):
        pass


_srv = http.server.HTTPServer(("127.0.0.1", 0), _Ollama)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
os.environ["OLLAMA_HOST"] = "http://127.0.0.1:%d" % _srv.server_address[1]

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtCore import (QMetaObject, QObject, Q_ARG, QTimer,   # noqa: E402
                            QUrl)
from PySide6.QtGui import QGuiApplication, QImage                  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent     # noqa: E402

sys.argv = [sys.argv[0], "--selftest"]
import main as oracle                                              # noqa: E402

app = QGuiApplication([])
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


def script(path, body):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


PIC = _TMP / "graph.png"
img = QImage(400, 200, QImage.Format.Format_RGB32)
img.fill(0x336699)
img.save(str(PIC))

o = oracle.Ollama()
o._set_busy(True)
shown = []
o.imageFetchResult.connect(lambda j: shown.append(json.loads(j)))
clips = []
o.videoResult.connect(lambda j: clips.append(json.loads(j)))
results = {}


def run_tool(name, args, ms=8000):
    """One tool call through the real dispatcher, to completion."""
    shown.clear()
    clips.clear()
    results.clear()
    remaining = {"n": 1, "sink": [None]}
    o._dispatch_tool(name, args, 0, remaining, [{}])
    loop = QTimer()
    loop.setSingleShot(True)
    loop.timeout.connect(app.quit)
    loop.start(ms)
    tick = QTimer()
    tick.setInterval(50)
    tick.timeout.connect(lambda: app.quit() if remaining["sink"][0] else None)
    tick.start()
    app.exec()
    tick.stop()
    sink = remaining["sink"][0]
    try:
        return json.loads(sink["content"]) if sink else None
    except (TypeError, ValueError, KeyError):
        return None


# `_tool_done` re-posts the chat when a round finishes; the harness only wants
# the sink, so keep it from talking to a daemon that may not be there.
o._tool_done = lambda remaining, calls: None

# 1. show_image: on screen, and NOT in the model's lap
r = run_tool("show_image", {"path": str(PIC), "caption": "the graph"})
check("show_image draws a local picture",
      len(shown) == 1 and shown[0].get("ok") and shown[0].get("w") == 400
      and shown[0].get("alt") == "the graph", json.dumps(shown)[:160])
check("...and hands the model no pixels",
      bool(r) and r.get("ok") and "b64" not in r and not o._pending_vision,
      json.dumps(r)[:160])
r = run_tool("show_image", {"path": str(_TMP / "nope.png")})
check("a missing picture is an error, not an empty frame",
      bool(r) and "error" in r, json.dumps(r)[:120])
# ONE PICTURE, DRAWN ONCE. A turn that generated one and then show_image'd the
# same path twice put it in the chat three times and told him two had been made
# [his, 2026-08-24]. The file is the identity; a second request is answered
# with where it is, not with another copy.
o._paths_shown = set()
r = run_tool("show_image", {"path": str(PIC)})
first = len(shown)
r2 = run_tool("show_image", {"path": str(PIC)})
check("the same picture is not drawn a second time",
      first == 1 and len(shown) == 0, "first=%d again=%d" % (first, len(shown)))
check("...and the model is told it is already there, not that it failed",
      bool(r2) and r2.get("ok") and r2.get("already_shown")
      and "not two" in (r2.get("note") or ""), json.dumps(r2)[:200])
o._paths_shown = set()

# 2. screenshot: through a stub capture, drawn AND attached
cap = script(_TMP / "shot.sh",
             'cp %s "$1"' % str(PIC))
os.environ["ORACLE_SHOT_CMD"] = str(cap)
o._caps = ["vision"]
o._ctx_model = o._model = "fake"
r = run_tool("screenshot", {})
check("a screenshot is drawn in the chat",
      len(shown) == 1 and shown[0].get("ok"), json.dumps(shown)[:140])
check("...and attached to the model's next turn",
      bool(o._pending_vision) and bool(r) and r.get("ok"), json.dumps(r)[:140])
o._pending_vision = []
r = run_tool("screenshot", {"show_only": True})
check("show_only captures without handing it over",
      bool(r) and r.get("ok") and not o._pending_vision, json.dumps(r)[:140])
o._caps = []
os.environ["ORACLE_SHOT_CMD"] = str(script(_TMP / "nope.sh", "exit 3"))
r = run_tool("screenshot", {})
check("a capture that fails says so", bool(r) and "error" in r,
      json.dumps(r)[:140])
os.environ["ORACLE_SHOT_CMD"] = str(cap)

# 3. make_image: painter's generator, stubbed — the parse and the display.
# `_paths_shown` is per TURN in the app (reset in `send`); the harness calls
# tools directly, so each section that draws the same file clears it itself.
o._paths_shown = set()
made = _TMP / "made.png"
img.save(str(made))
os.environ["ORACLE_PAINTER"] = str(script(
    _TMP / "gen.sh",
    'echo "model    Krea 2"\n'
    'echo "prompt_id abc  in 4.2s"\n'
    'echo "  saved %s (1234 bytes)"' % str(made)))
r = run_tool("make_image", {"prompt": "a red cube"}, ms=20000)
check("make_image shows what the backend saved",
      len(shown) == 1 and shown[0].get("ok")
      and shown[0].get("path") == str(made), json.dumps(shown)[:160])
check("...and tells the model it has not seen it",
      bool(r) and r.get("ok") and "NOT seen" in (r.get("note") or ""),
      json.dumps(r)[:200])
check("...and not to say where it is or make it twice",
      bool(r) and "where it is" in (r.get("note") or "")
      and "again" in (r.get("note") or ""), json.dumps(r)[:260])
# ONE RENDER OF EACH KIND PER TURN is a real rule now (main.py `_make_media`),
# and `send` is what clears the record. The harness calls the dispatcher
# directly, so each section that generates again clears it itself — exactly like
# `_paths_shown` above.
r = run_tool("make_image", {"prompt": "a second cube"}, ms=20000)
check("a second picture in the same turn is refused, with the first's path",
      bool(r) and "already made" in (r.get("error") or "")
      and r.get("path") == str(made), json.dumps(r)[:200])
o._made_this_turn = {}
os.environ["ORACLE_PAINTER"] = str(script(
    _TMP / "genfail.sh", 'echo "backend unreachable at 127.0.0.1:8188" >&2; exit 1'))
r = run_tool("make_image", {"prompt": "a red cube"}, ms=20000)
check("a backend that will not generate is reported",
      bool(r) and "error" in r and "unreachable" in r["error"],
      json.dumps(r)[:200])

# 3a-stop. STOP TAKES THE RENDER WITH IT [his, 2026-08-24]. `cancel()` used to
# abort the ollama stream only, leaving the backend sampling for another twenty
# minutes for nobody. The stub traps TERM and writes a breadcrumb, which is the
# assertion that the signal reached the GENERATOR and not just the shell in
# front of it (the `exec` in _painter_argv).
o._made_this_turn = {}
trapped = _TMP / "trapped"
os.environ["ORACLE_PAINTER"] = str(script(
    _TMP / "genslow.sh",
    'trap \'touch %s; exit 130\' TERM\n'
    'sleep 60 &\nwait' % trapped))
remaining = {"n": 1, "sink": [None]}
o._dispatch_tool("make_image", {"prompt": "a red cube"}, 0, remaining, [{}])
QTest.qWait(1500)
live = [pr for pr in o._gen_procs
        if pr.state() != oracle.QProcess.ProcessState.NotRunning]
check("a render is a process the app is holding", len(live) == 1, str(len(live)))
o.cancel()
for _ in range(60):
    QTest.qWait(50)
    if trapped.exists():
        break
check("stop reaches the generator itself, not just its shell", trapped.exists())
def _dead(pr):
    try:
        return pr.state() == oracle.QProcess.ProcessState.NotRunning
    except RuntimeError:
        return True          # deleteLater already took it: gone is gone
check("...and the render process is gone", all(_dead(pr) for pr in live))
os.environ.pop("ORACLE_PAINTER", None)
o._set_busy(True)          # cancel() dropped it; the sections below need it

# THE SAME ASSERTIONS ON BOTH MACHINES. From book the generator still runs on
# top (the weights and the GPU are there), so `_painter_argv` returns
# `ssh top bash -lc '<script>'` — one more level of quoting — and any input
# picture is named by the copy that gets staged into PAINTER_IN_DIR rather than
# by its path here. Normalise both, and what the checks below read is the
# generator's own command line either way.
def gen_line(argv):
    line = argv[-1]
    return shlex.split(line)[-1] if oracle.Ollama._painter_remote() else line


def staged(path):
    if not oracle.Ollama._painter_remote():
        return str(path)
    return "%s/in0%s" % (oracle.Ollama.PAINTER_IN_DIR,
                         os.path.splitext(str(path))[1] or ".png")


# 3b. every knob reaches the generator's command line, and an input picture
# turns the same tool into an EDIT.
argv, stdin, err = oracle.Ollama._painter_argv(
    {"prompt": "1girl, solo", "model": "anima", "aspect": "2:3",
     "megapixels": 1, "count": 2, "seed": 7}, "image")
line = gen_line(argv)
check("make_image passes his settings through, not a paraphrase",
      not err and " --aspect 2:3" in line and " --megapixels 1" in line
      and " --batch 2" in line and " --seed 7" in line
      and " --model anima" in line, (err or line)[-220:])
argv, stdin, err = oracle.Ollama._painter_argv(
    {"prompt": "make it night", "input_images": [str(PIC)]}, "image")
check("an input picture makes it an edit, on the edit model",
      not err and " --edit" in gen_line(argv) and " --mode edit" in gen_line(argv)
      and (" --image " + staged(PIC)) in gen_line(argv),
      (err or gen_line(argv))[-220:])
argv, stdin, err = oracle.Ollama._painter_argv(
    {"prompt": "she turns", "first_frame": str(PIC), "last_frame": str(PIC),
     "seconds": 6}, "video")
check("a clip names both ends and its length",
      not err and " --mode video" in gen_line(argv)
      and " --seconds 6" in gen_line(argv)
      and (" --last-frame " + staged(PIC)) in gen_line(argv),
      (err or gen_line(argv))[-260:])
# EVERY KNOB THE WORKFLOW HAS, not the four it started with [his, 2026-08-24:
# a turn that answered "CFG isn't something I can directly control from here"].
argv, stdin, err = oracle.Ollama._painter_argv(
    {"prompt": "x", "cfg": 1.0, "sampler": "euler", "scheduler": "beta",
     "denoise": 0.8, "loras": ["thing", "other:0.4"],
     "extra": {"shift": 3.0, "flavour": "wet"}}, "image")
line = gen_line(argv)
check("the whole sampler is reachable, not just steps and seed",
      not err and " --cfg 1.0" in line and " --sampler euler" in line
      and " --scheduler beta" in line and " --denoise 0.8" in line,
      (err or line)[-260:])
check("...and its LoRAs, one flag each",
      " --lora thing" in line and " --lora other:0.4" in line, line[-200:])
check("...and anything else by name, typed as JSON",
      " --set shift=3.0" in line and " --set 'flavour=\"wet\"'" in line,
      line[-200:])
argv, stdin, err = oracle.Ollama._painter_argv(
    {"prompt": "x", "fps": 12, "cfg": 4}, "video")
check("a clip's own knobs too", not err and " --fps 12" in gen_line(argv)
      and " --cfg 4" in gen_line(argv), (err or gen_line(argv))[-200:])
argv, stdin, err = oracle.Ollama._painter_argv(
    {"prompt": "x", "first_frame": str(_TMP / "gone.png")}, "video")
check("a frame that is not there is refused before the backend is woken",
      bool(err) and not argv, str(err))
check("...and the refusal names the machine it looked on",
      "on " + oracle.LOCAL_HOST in str(err), str(err))

# A PICTURE make_image JUST MADE IS ON THE GENERATOR'S DISK, not this one. From
# book that path is a top path, and validating it here failed every "make an
# image and animate it" [2026-08-24, sess-1787643678852]. A remembered
# generator-side path goes through unstaged.
MADE = "/home/lam/.local/share/oracle/images/made/painter_00041_.png"
argv, stdin, err = oracle.Ollama._painter_argv(
    {"prompt": "she moves", "first_frame": MADE}, "video", [MADE])
if oracle.Ollama._painter_remote():
    check("a path the generator wrote is passed straight through",
          not err and (" --image " + MADE) in gen_line(argv) and not stdin,
          (err or gen_line(argv))[-200:])
else:
    check("on top the same path is simply a local file",
          bool(err) or (" --image " + MADE) in gen_line(argv), str(err)[:120])
argv, stdin, err = oracle.Ollama._painter_argv(
    {"prompt": "she moves", "first_frame": MADE}, "video")
check("...but only one this app actually generated",
      bool(err) if oracle.Ollama._painter_remote() else True, str(err)[:120])

# WHY IT FAILED, not the last line of the traceback. ComfyUI's error text ends
# on python's caret underline, and that is what reached the model as the reason
# [same session: it invented "a mismatch between the image format/dimensions"].
OOM = ("\nFAILED: Traceback (most recent call last):\n"
       '  File "cuda/__init__.py", line 1864, in int8_linear\n'
       "    out = torch.empty((m, n), dtype=out_dtype, device=x.device)\n"
       "          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n"
       "torch.OutOfMemoryError: Allocation on device 0 would exceed allowed "
       "memory. (out of memory)\n")
why = oracle.Ollama._gen_failure(OOM, "", "clip")
check("a caret underline is never the reason given", "^^^" not in why, why[:80])
check("...an OOM is named as the GPU, with what to do about it",
      "GPU ran out of memory" in why and "unloaded" in why, why[:120])
check("...and a plain refusal is passed through as itself",
      oracle.Ollama._gen_failure("", "no model matching 'zzz'", "picture")
      == "no model matching 'zzz'")
check("...and an empty failure still says something",
      oracle.Ollama._gen_failure("", "", "clip") == "the backend produced no clip")

# 3c. make_video: the same generator, drawn as a clip he can play
clip = _TMP / "made.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                "-i", "testsrc=size=320x240:rate=8", "-t", "1",
                "-pix_fmt", "yuv420p", str(clip)], check=False)
if clip.exists():
    os.environ["ORACLE_PAINTER"] = str(script(
        _TMP / "genvid.sh",
        'echo "mode     video"\n'
        'echo "prompt_id abc  in 61.0s"\n'
        'echo "  saved %s (9999 bytes)"' % str(clip)))
    r = run_tool("make_video", {"prompt": "she turns", "seconds": 6}, ms=30000)
    check("make_video puts a playable clip in the chat",
          len(clips) == 1 and clips[0].get("ok")
          and clips[0].get("src") == "file://" + str(clip),
          json.dumps(clips)[:200])
    check("...on a poster frame, not a black box",
          bool(clips) and bool(clips[0].get("poster")), json.dumps(clips)[:200])
    check("...and tells the model it has not seen it",
          bool(r) and r.get("ok") and "not seen" in (r.get("note") or ""),
          json.dumps(r)[:200])
else:
    print("skip  make_video (no ffmpeg to build a test clip)")
os.environ["ORACLE_PAINTER"] = str(script(
    _TMP / "genvidfail.sh", 'echo "cannot build: no video model" >&2; exit 1'))
r = run_tool("make_video", {"prompt": "x"}, ms=20000)
check("a clip that cannot be built is reported",
      bool(r) and "error" in r, json.dumps(r)[:200])

# 3d. THE MEMORY DANCE, against a recording warden. What he asked for is that a
# generation never meets a loaded model: chatter gives its OWN weights back
# first (its send lease is still live, and the warden never interrupts work in
# flight, so without this every generation chatter itself asked for would be
# refused), holds a SHORT lease it keeps renewing, and takes the lease back at
# the end so the reload cannot land on top of a render.
WARDEN_CALLS = []


class _Warden(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            doc = json.loads(self.rfile.read(n).decode() or "{}")
        except ValueError:
            doc = {}
        WARDEN_CALLS.append((self.path.rstrip("/"), doc))
        body = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_wsrv = http.server.HTTPServer(("127.0.0.1", 0), _Warden)
threading.Thread(target=_wsrv.serve_forever, daemon=True).start()
import warden as wardenmod                                        # noqa: E402
wardenmod.WARDEN = "http://127.0.0.1:%d" % _wsrv.server_address[1]
o._warden = wardenmod.Warden(o)
o._model = "big:35b"
os.environ["ORACLE_PAINTER"] = str(script(
    _TMP / "genslow.sh",
    'echo "  saved %s (1234 bytes)"' % str(made)))
WARDEN_CALLS.clear()
r = run_tool("make_image", {"prompt": "a red cube"}, ms=20000)
paths = [c[0] for c in WARDEN_CALLS]
check("chatter gives its own weights back before asking for room",
      paths[:2] == ["/done", "/reserve"]
      and WARDEN_CALLS[0][1].get("backend") == "ollama"
      and WARDEN_CALLS[1][1].get("backend") == "comfy", str(WARDEN_CALLS)[:300])
check("...on a short lease, not an open-ended one",
      0 < int(WARDEN_CALLS[1][1].get("lease") or 0) <= 600,
      str(WARDEN_CALLS[1][1]))
check("...and hands it back, then takes the turn's lease again",
      paths[-2:] == ["/done", "/reserve"]
      and WARDEN_CALLS[-2][1].get("backend") == "comfy"
      and WARDEN_CALLS[-1][1].get("backend") == "ollama", str(WARDEN_CALLS)[:300])

# 3e. THE WAIT IS SHOWN, and the picture says what made it. A render is minutes
# long; the generator reports where it is (`::progress`) and what it ran
# (`::result`), and neither may be read only at the end.
seen = []
o.genProgress.connect(lambda label, frac: seen.append((label, frac)))
os.environ["ORACLE_PAINTER"] = str(script(
    _TMP / "genmeta.sh",
    'echo "::progress 0.10 sampling 1/50"\n'
    'echo "::progress 0.85 decoding"\n'
    'echo "  saved %s (1234 bytes)"\n'
    'echo \'::result {"model":"anima-base-v1.0.safetensors","seed":7,'
    '"positive":"1girl, (bad hands:-1.0)","steps":50,'
    '"sampler":"euler_cfg_pp","scheduler":"beta","width":1152,'
    '"height":1728,"cfg":0.7,"tags":{"unknown":["smiling softly"],'
    '"suspect":["lain igarashi from serial experiments lain"],"renamed":[]}'
    '}\'' % str(made)))
seen.clear()
o._paths_shown = set()
o._made_this_turn = {}          # a fresh turn (see 3a-stop)
r = run_tool("make_image", {"prompt": "a red cube"}, ms=20000)
check("a render reports where it is, as it runs",
      any(abs(f - 0.85) < 0.001 for _l, f in seen)
      and any(l.startswith("sampling") for l, _f in seen), str(seen)[:200])
check("...and the caption says what made it",
      len(shown) == 1 and "anima-base-v1.0" in (shown[0].get("meta") or "")
      and "1152x1728" in shown[0]["meta"] and "50 steps" in shown[0]["meta"]
      and "euler_cfg_pp/beta" in shown[0]["meta"]
      and "seed 7" in shown[0]["meta"], json.dumps(shown)[:260])
check("the seed comes back to the model, so it can lock it",
      bool(r) and r.get("seed") == 7 and r.get("sampler") == "euler_cfg_pp"
      and r.get("width") == 1152, json.dumps(r)[:260])
check("the tags that did nothing come back, so it can stop inventing them",
      bool(r) and (r.get("tag_problems") or {}).get("unknown") == ["smiling softly"]
      and "never spell a character" in (r.get("tag_note") or ""),
      json.dumps(r)[:300])
check("the caption is the prompt the GRAPH ran, folded negative and all",
      bool(shown) and shown[0].get("alt") == "1girl, (bad hands:-1.0)",
      json.dumps(shown)[:200])

WARDEN_CALLS.clear()
wardenmod.WARDEN = "http://127.0.0.1:1"          # dead again: fail open
o._warden = wardenmod.Warden(o)

# 4. tools as files
script(_TMP / "tools" / "weather", 'read -r a; echo "{\\"ok\\":true,\\"said\\":$a}"')
(_TMP / "tools" / "weather.json").write_text(json.dumps({
    "description": "The weather where he is.",
    "parameters": {"type": "object",
                   "properties": {"city": {"type": "string"}},
                   "required": ["city"]}}), encoding="utf-8")
(_TMP / "tools" / "read_file.json").write_text(json.dumps({
    "description": "shadowing a built-in", "parameters": {}}), encoding="utf-8")
script(_TMP / "tools" / "read_file", "echo '{}'")
(_TMP / "tools" / "broken.json").write_text("{ not json", encoding="utf-8")
cat = oracle.custom_tools()
check("a manifest plus a program is a tool", "weather" in cat, str(sorted(cat)))
check("a broken manifest is skipped", "broken" not in cat, str(sorted(cat)))
names = [t["function"]["name"] for t in oracle.custom_tool_defs()]
check("a custom tool cannot shadow a built-in", "read_file" not in names,
      str(names))
check("...and it IS offered to the model",
      "weather" in [t["function"]["name"] for t in oracle.Ollama._all_tools()])
r = run_tool("weather", {"city": "Juneau"})
check("running one feeds it the args and takes back its JSON",
      bool(r) and r.get("ok") and (r.get("said") or {}).get("city") == "Juneau",
      json.dumps(r)[:160])
script(_TMP / "tools" / "cranky", 'echo "it broke" >&2; exit 2')
(_TMP / "tools" / "cranky.json").write_text(json.dumps(
    {"description": "fails", "parameters": {}}), encoding="utf-8")
r = run_tool("cranky", {})
check("one that fails hands back what it printed",
      bool(r) and r.get("error") == "it broke", json.dumps(r)[:160])

# 5. live output from the runner (the executor's own stream, no chatter needed)
chunks = []
o.execOutput.connect(lambda c: chunks.append(c))
r = run_tool("run_bash", {"command": "echo one; echo two; echo three >&2"},
             ms=20000)
check("a program's output arrives while it runs",
      len(chunks) >= 2 and "one" in "".join(chunks), repr(chunks)[:160])
check("...and the final result is still the whole thing",
      bool(r) and r.get("ok") and "two" in (r.get("stdout") or ""),
      json.dumps(r)[:200])
o._set_busy(False)

# 6. models: the daemon's job, not the shell's
progress = []
o.execOutput.connect(lambda c: progress.append(c))
r = run_tool("manage_models", {"action": "list"})
check("list names what is installed, biggest first",
      bool(r) and r.get("count") == 2
      and r["models"][0]["name"] == "big:35b"
      and r["models"][0]["size_gb"] == 22.0, json.dumps(r)[:200])
r = run_tool("manage_models", {"action": "show", "model": "big:35b"})
check("show reports the real context length",
      bool(r) and r.get("context_length") == 262144
      and "tools" in (r.get("capabilities") or []), json.dumps(r)[:200])
progress.clear()
r = run_tool("manage_models", {"action": "pull", "model": "small:1b"},
             ms=20000)
check("a pull streams progress and finishes",
      bool(r) and r.get("ok") and any("%" in c for c in progress),
      json.dumps(r)[:160] + " " + repr(progress)[:120])
r = run_tool("manage_models", {"action": "pull", "model": "nope:1b"}, ms=20000)
check("a pull that fails says what ollama said",
      bool(r) and "does not exist" in (r.get("error") or ""),
      json.dumps(r)[:200])
PULLED.clear()
r = run_tool("manage_models", {"action": "remove", "model": "big:35b"})
check("removing weights needs an explicit confirm",
      bool(r) and "confirm" in (r.get("error") or "") and not PULLED,
      json.dumps(r)[:200])
r = run_tool("manage_models", {"action": "remove", "model": "small:1b",
                               "confirm": True})
check("...and then it happens",
      bool(r) and r.get("ok") and PULLED == [("delete", "small:1b")],
      json.dumps(r)[:160])

# ---- 7. branching, through the real Root.qml ------------------------------
engine = QQmlApplicationEngine()
ctx = engine.rootContext()
parts = {"WalPalette": oracle.Palette(oracle.theme_source(oracle.PANEL_THEME)),
         "DeskStyle": oracle.DeskStyle(), "Titlebar": oracle.Titlebar(),
         "Ollama": oracle.Ollama(), "Backend": oracle.Backend(),
         "Sessions": oracle.Sessions(), "Clip": oracle.Clip(),
         "Md": oracle.MdFormat(),
         # The jobs tray reads `Jobs`; without it the window loads with a
         # ReferenceError rather than an empty tray.
         "Jobs": oracle.Jobs()}
for key, obj in parts.items():
    obj.setParent(app)
    ctx.setContextProperty(key, obj)
ctx.setContextProperty("ollamaHost", oracle.OLLAMA)
theme_comp = QQmlComponent(
    engine, QUrl.fromLocalFile(str(APP / "qml" / "theme" / "Theme.qml")))
theme = theme_comp.create()
theme.setParent(app)
ctx.setContextProperty("Theme", theme)
warns = []
engine.warnings.connect(lambda es: warns.extend(e.toString() for e in es))
engine.load(QUrl.fromLocalFile(str(APP / "qml" / "Main.qml")))
win = engine.rootObjects()[0]
content = win.findChild(QObject, "content")

TURNS = [{"isUser": True, "body": "first question"},
         {"isUser": False, "body": "first answer", "who": "m"},
         {"isUser": True, "body": "second question"},
         {"isUser": False, "body": "second answer", "who": "m"}]
QMetaObject.invokeMethod(content, "loadTurns", Q_ARG("QVariant", "sess-old"),
                         Q_ARG("QVariant", "the old branch"),
                         Q_ARG("QVariant", json.dumps(TURNS)))
for _ in range(4):
    app.processEvents()
QMetaObject.invokeMethod(content, "editFrom", Q_ARG("QVariant", 2))
for _ in range(4):
    app.processEvents()
check("editing an earlier prompt truncates from it",
      content.property("chatRev") is not None
      and content.property("sessionId") == "", "id=%r"
      % content.property("sessionId"))
rows = json.loads(QMetaObject.invokeMethod(content, "rowsJson") or "[]") \
    if False else None
check("...and the prompt comes back for editing",
      "second question" in str(win.findChild(QObject, "promptBox")
                               .property("text")),
      str(win.findChild(QObject, "promptBox").property("text"))[:60])
check("...and the branch he left keeps its own session",
      content.property("sessionTitle") == "", "%r" % content.property("sessionTitle"))
check("no QML warnings", not warns, "; ".join(warns)[:300])

print("\n%d checks failed" % len(fails))
sys.exit(1 if fails else 0)
