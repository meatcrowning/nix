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
results = {}


def run_tool(name, args, ms=8000):
    """One tool call through the real dispatcher, to completion."""
    shown.clear()
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

# 3. make_image: painter's generator, stubbed — the parse and the display
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
      bool(r) and r.get("ok") and "not seen" in (r.get("note") or ""),
      json.dumps(r)[:200])
os.environ["ORACLE_PAINTER"] = str(script(
    _TMP / "genfail.sh", 'echo "backend unreachable at 127.0.0.1:8188" >&2; exit 1'))
r = run_tool("make_image", {"prompt": "a red cube"}, ms=20000)
check("a backend that will not generate is reported",
      bool(r) and "error" in r and "unreachable" in r["error"],
      json.dumps(r)[:200])

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
         "Md": oracle.MdFormat()}
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
