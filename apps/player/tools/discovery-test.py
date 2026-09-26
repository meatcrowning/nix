#!/usr/bin/env python3
"""Hermetic discovery, acquisition, preview and QML probes; no live services."""
import copy
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent.parent
try:
    import PySide6
except ImportError:
    wrapper = Path(shutil.which("player")).read_text()
    found = re.search(r'/nix/store/[^" ]+-env/bin/python3[0-9.]*', wrapper)
    python = found.group() if found else "/usr/bin/python3"
    os.execv(python, [python, __file__])

scratch = tempfile.TemporaryDirectory(prefix="player-discover-test-")
root = Path(scratch.name)
for name in ("HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR"):
    os.environ[name] = str(root / name)
    Path(os.environ[name]).mkdir(mode=0o700)
os.environ.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_CONTROLS_STYLE="Basic", DESK_SESSION="hypr",
                  PLAYER_LIBRARY_ROOT=str(root / "music"), LASTFM_CONFIG=str(root / "missing-account.json"))
for name in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "PULSE_SERVER", "PIPEWIRE_REMOTE"):
    os.environ.pop(name, None)
if not sys.executable.startswith("/nix/store"):
    os.environ.pop("QT_PLUGIN_PATH", None)
    os.environ.pop("QT_STYLE_OVERRIDE", None)
Path(os.environ["PLAYER_LIBRARY_ROOT"]).mkdir()
sys.path[:0] = [str(HERE), str(HERE.parent / "pylib")]

from PySide6.QtCore import QObject, QUrl, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine, QQmlComponent
from discovery import Catalog, identity, preview_url
from discoveryacquire import complete_candidate, acquire, reconcile, DeferredAcquisition
import urllib.request
urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected real network"))
import main as P
app = QGuiApplication([])
assert app.platformName() == "offscreen"


def check(name, assertion):
    assert assertion, name
    print("ok", name)


db = root / "library.db"
with sqlite3.connect(db) as con:
    con.execute("CREATE TABLE tracks(id INTEGER, album_id INTEGER, artist TEXT, album_artist TEXT, album TEXT, title TEXT, rating REAL, favorite INTEGER, play_count INTEGER, last_played REAL)")
    con.execute("INSERT INTO tracks VALUES(1,1,'Seed','Seed','Owned','Local',1,1,12,?)", (time.time(),))

release = {"collectionId": 42, "artistName": "Other", "collectionName": "Unheard - EP", "releaseDate": "2026-01-01", "collectionViewUrl": "https://music.apple.com/album/42", "trackCount": 2, "wrapperType": "collection"}
tracks = [{"kind": "song", "collectionId": 42, "trackName": name, "artistName": "Other", "trackNumber": n,
           "trackTimeMillis": 120000, "previewUrl": "https://audio-ssl.itunes.apple.com/preview.m4a"} for n, name in enumerate(("First", "Second"), 1)]

def fetch(url):
    return {"results": [release] + tracks} if "/lookup?" in url else {"results": [release]}


def fm(method, args):
    return {"similarartists": {"artist": {"name": "Other", "match": "0.8"}}}

cat = Catalog(db, root, fetch=fetch, lastfm_call=fm)
cat.refresh()
check("new artist seeded by actual evidence", len(cat.visible()) == 1 and cat.visible()[0]["reason"] == "Similar to Seed")
key = cat.visible()[0]["key"]
item = cat.resolve(key)
check("complete EP tracklist with previews", item["resolved"] and len(item["tracks"]) == 2)
check("edition matching", identity("Seed", "Owned (Deluxe Edition)") == identity("Seed", "Owned"))
check("reject unsafe preview URLs", not any(preview_url(u) for u in ("file:///etc/passwd", "https://itunes.apple.com.evil.test/a", "http://itunes.apple.com/a", "https://x@itunes.apple.com/a")))
cat.state["feedback"][key] = {"saved": True, "dismissed": True}
cat.save()
check("dismissal persists", Catalog(db, root).visible() == [])
cat.state["feedback"][key].pop("dismissed")
cat.save()

response = {"username": "peer", "hasFreeUploadSlot": True, "files": [
    {"filename": "Other\\Unheard\\%02d %s.flac" % (i, t["title"]), "length": 120, "size": 1000000} for i, t in enumerate(item["tracks"], 1)]}
check("complete album accepted", len(complete_candidate(item, [response], "lossless")[1]) == 2)
for label, bad in (("partial", {**response, "files": response["files"][:1]}),
                   ("wrong duration", {**response, "files": [{**f, "length": 160} for f in response["files"]]}),
                   ("wrong edition", {**response, "files": [{**f, "filename": f["filename"].replace("First", "First Live")} for f in response["files"]]})):
    try:
        complete_candidate(item, [bad], "lossless")
        raise AssertionError(label + " accepted")
    except ValueError:
        print("ok reject", label)

# Real receipt serializer and real response parser, fake transport only.
spec = importlib.util.spec_from_file_location("test_slsk", HERE / "tools/soulseek-missing.py")
slsk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(slsk)
slsk.DUMP_DIR = str(root / "pipeline")
slsk.DEFAULT_KEY_FILE = str(root / "key")
Path(slsk.DEFAULT_KEY_FILE).write_text("fixture")
posts = []

def http(method, url, api_key, data=None):
    if method == "POST":
        posts.append((url, data))
        return {"id": "fixture-search"}
    if url.endswith("/responses"):
        return [response]
    return {"state": "Completed"}
slsk.http = http
class Stop:
    def wait(self, duration): return False
    def is_set(self): return False
acquire(cat, key, os.environ["PLAYER_LIBRARY_ROOT"], Stop(), slsk=slsk, host="top")
check("one album transfer and durable receipt", len(posts) == 2 and cat.state["requests"][key]["status"] == "queued")
state = slsk.load_state(str(Path(slsk.DUMP_DIR) / "soulseek-state.tsv"))
check("importer identity accompanies every track", len(state) == 2 and all(r["album"] == item["album"] for r in state.values()))
acquire(cat, key, os.environ["PLAYER_LIBRARY_ROOT"], Stop(), slsk=slsk, host="top")
check("repeat acquisition is inert", len(posts) == 2)
try:
    acquire(cat, key, os.environ["PLAYER_LIBRARY_ROOT"], Stop(), slsk=slsk, host="book")
    raise AssertionError("book acquired")
except ValueError:
    print("ok book acquisition stays on top")
slsk.http = lambda *a: [{"directories": [{"files": [{"username": "peer", "filename": f["filename"], "state": "Completed, Succeeded"} for f in response["files"]]}]}]
reconcile(cat, slsk)
check("transfer status parser", cat.state["requests"][key]["status"] == "downloaded")
# Limits and uncertain POSTs must refuse duplicate automatic work.
original_state = copy.deepcopy(cat.state)
cat.state["requests"] = {"previous": {"status":"queued", "when":time.time(), "bytes":1}}
cat.settings.update(mode="automatic", host="top", weekly=1)
try:
    acquire(cat, key, os.environ["PLAYER_LIBRARY_ROOT"], Stop(), automatic=True, slsk=slsk, host="top")
    raise AssertionError("weekly limit ignored")
except DeferredAcquisition:
    print("ok automatic weekly gate")
cat.settings["weekly"] = 10
slsk.DUMP_DIR = str(root / "uncertain-pipeline")
cat.state["requests"] = {}

cat.settings["budget"] = 1
large_response = {**response, "files": [{**f, "size": 1024**3} for f in response["files"]]}
slsk.http = lambda method, url, api_key, data=None: [large_response] if url.endswith("/responses") else http(method, url, api_key, data)
try:
    acquire(cat, key, os.environ["PLAYER_LIBRARY_ROOT"], Stop(), slsk=slsk, host="top")
    raise AssertionError("byte budget ignored")
except DeferredAcquisition:
    print("ok storage budget rejects before enqueue")
check("budget rejection has no transfer receipt", not cat.state["requests"])
class Cancelled(Stop):
    def wait(self, duration): return True
    def is_set(self): return True
slsk.http = http
acquire(cat, key, os.environ["PLAYER_LIBRARY_ROOT"], Cancelled(), slsk=slsk, host="top")
check("cancelled search cannot enqueue", not cat.state["requests"])
cat.settings["budget"] = 2

def uncertain(method, url, api_key, data=None):
    if method == "POST" and "/transfers/" in url:
        raise OSError("fixture timeout after acceptance")
    return http(method, url, api_key, data)
slsk.http = uncertain
try:
    acquire(cat, key, os.environ["PLAYER_LIBRARY_ROOT"], Stop(), slsk=slsk, host="top")
    raise AssertionError("expected timeout")
except OSError:
    pass
check("uncertain POST persisted before retry", Catalog(db, root).state["requests"][key]["status"] == "checking transfer")
count = len(posts)
acquire(cat, key, os.environ["PLAYER_LIBRARY_ROOT"], Stop(), slsk=slsk, host="top")
check("uncertain POST never automatically repeated", len(posts) == count)
cat.state = original_state
cat.settings = cat.state["settings"]
cat.save()
with sqlite3.connect(db) as con:
    for n, title in enumerate(("First", "Second"), 2):
        con.execute("INSERT INTO tracks VALUES(?,2,'Other','Other','Unheard',?,0,0,0,0)", (n,title))
check("import turns recommendation into Play", cat.visible()[0]["albumId"] == 2)

import mpv as mpvlib

class FakeMpv:
    mpv_version_tuple = (0, 41, 0)
    loadfile = mpvlib.MPV.loadfile
    def __init__(self): self.commands = []; self.pause = False
    def command(self, *args): self.commands.append(args)
    def __setitem__(self, k, v): pass

class Library:
    def tracks_by_ids(self, ids): return [{"id": i, "path": "/fixture/%s.flac" % i, "title": "Local", "duration":120} for i in ids]
    def album(self, aid): return {}
    def bump_playcount(self, *args): raise AssertionError("preview counted")

saved_prefs = {}
p = P.Player.__new__(P.Player)
QObject.__init__(p)
p._library = Library(); p._mpv = FakeMpv()
p._prefs = types.SimpleNamespace(set=lambda key, value: saved_prefs.update({key:value}))
p._queue = p._library.tracks_by_ids([1,2]); p._orig_queue = list(reversed(p._queue))
p._index = 1; p._position = 43.25; p._duration = 120; p._playing = True
p._shuffle = True; p._loop = 2; p._listened = 17; p._counted = False; p._started_at = 123
p._mpv_base = 0; p._mpv_fill_token = 0; p._mpv_fill_pending = False; p._mpv_loaded_until = -1
p._mpv_paused = False; p._idle = False; p._seek_target = None; p._seek_at = 0
p._rg_mode = "off"; p._rg_preamp = 0; p._rg_fallback = 0
p._scrobbler = types.SimpleNamespace(nowPlaying=lambda t: check("never announce preview", t["id"] > 0))
queue_before = p._queue; orig_before = p._orig_queue
p.startPreview(item, -1)
check("preview uses existing engine with temporary ids", p.previewing and len(p._queue) == 2 and p._queue[0]["id"] < 0)
p._listened = 300; p._maybe_count()
p._preview_path(item["tracks"][0]["preview"]); p._on_idle(True)
check("restore does not inject a stale stop/idle event", not any(c[0] == "stop" for c in p._mpv.commands))
check("EOF restores exact queue and shuffle order", not p.previewing and p._queue is queue_before and p._orig_queue is orig_before)
check("EOF restores position and listen counters", p._position == 43.25 and p._listened == 17 and p._loop == 2)
check("seek is per-file before playback", p._mpv.commands[-1][-1] == "start=43.25")
p._playing = False
p.startPreview(item, 1); p.endPreview()
check("paused session stays paused", p._mpv.pause)
p.startPreview(item, 0); p.save_state()
check("previews never enter saved queue", saved_prefs["queue"]["ids"] == [1,2])
p.startPreview(item, 0)
with patch.object(P, "library_is_remote_cached", return_value=True):
    p.queueTracks([3])
check("queue edits preserve original music", not p.previewing and [r["id"] for r in p._queue] == [1,2,3])

# Real QObject backend + real QML with network disabled and fixed catalog rows.
from discoverybridge import Discovery
bridge = Discovery(db, root, os.environ["PLAYER_LIBRARY_ROOT"], p)
bridge.activate = lambda: None
bridge._snapshot = {"items": [dict(item, saved=False, liked=False, status="", detail="", albumId=0, art="")], "settings":cat.settings, "busy":False, "message":""}
engine = QQmlEngine()
ctx = engine.rootContext()
ctx.setContextProperty("Player", p)
ctx.setContextProperty("Discovery", bridge)
palette = P.Palette(root / "palette.json")
ctx.setContextProperty("WalPalette", palette)
prefs = P.Prefs()
ctx.setContextProperty("Prefs", prefs)
from deskstyle import DeskStyle
style = DeskStyle()
ctx.setContextProperty("DeskStyle", style)
from glyphs import Glyphs
glyphs = Glyphs(); ctx.setContextProperty("GlyphMap", glyphs)
warnings = []
qInstallMessageHandler(lambda kind, context, text: warnings.append(text))
theme_component = QQmlComponent(engine, QUrl.fromLocalFile(str(HERE / "qml/theme/Theme.qml")))
theme = theme_component.create()
assert theme, theme_component.errorString()
ctx.setContextProperty("Theme", theme)
component = QQmlComponent(engine)
component.setData(b'import QtQuick\nItem { width: 460; height: 800; DiscoverView { objectName: "discover"; anchors.fill: parent; expanded: "' + key.encode() + b'" } }', QUrl.fromLocalFile(str(HERE / "qml/discovery-harness.qml")))
view = component.create()
assert view, component.errorString()
for _ in range(5): app.processEvents()
check("QML sees preview properties", p.metaObject().indexOfProperty("previewing") >= 0)
check("discovery view constructs", view.findChild(QObject,"discoveryList") is not None)
# Missing desktop palette fixtures are unrelated; component errors are not.
errors = [w for w in warnings if any(s in w for s in ("ReferenceError", "TypeError", "Cannot assign", "Cannot specify", "is not a type", "Binding loop"))]
check("QML has no binding/type errors: " + " | ".join(errors), not errors)
# Durable settings and feedback survive a restart and replay only once.
bridge.configure("weekly", 5)
bridge.feedback(key, "liked")
deadline = time.monotonic() + 2
while bridge._outbox and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(.01)
check("worker acknowledges durable local edits", not bridge._outbox)
stored = Catalog(db, root)
check("settings and feedback persisted", stored.settings["weekly"] == 5 and stored.state["feedback"][key]["liked"])
view.deleteLater(); app.processEvents(); bridge.shutdown()
# Native selector builds the same feature with native control adapters.
from PySide6.QtQml import QQmlFileSelector
selector = QQmlFileSelector(engine)
selector.setExtraSelectors(["plasma"])
engine.clearComponentCache()
native = QQmlComponent(engine, QUrl.fromLocalFile(str(HERE / "qml/DiscoverView.qml")))
native_view = native.create()
assert native_view, native.errorString()
for width in (240, 460, 800):
    native_view.setProperty("width", width)
    native_view.setProperty("height", 800)
    native_view.setProperty("showSettings", True)
    for _ in range(3): app.processEvents()
    check("native discovery layout at " + str(width), native_view.findChild(QObject,"discoveryList").property("height") > 0)
errors = [w for w in warnings if any(s in w for s in ("ReferenceError", "TypeError", "Cannot assign", "Cannot specify", "is not a type", "Binding loop"))]
check("native QML has no binding/type errors: " + " | ".join(errors), not errors)
native_view.deleteLater(); app.processEvents()
# Construct the complete Player on both faces with fake mpv and no service access.
(root / "mpv.py").write_text("class MPV:\n"
    "    def __init__(self, **kw): self.volume=100; self.pause=True; self.playlist_count=0; self.playlist_pos=0\n"
    "    def property_observer(self, name): return lambda fn: fn\n"
    "    def command(self, *args): pass\n"
    "    def __setitem__(self, key, value): pass\n")
for face in ("hypr", "plasma"):
    env = dict(os.environ, PYTHONPATH=str(root), DESK_SESSION=face, PLAYER_VIEW="discover",
               QT_QPA_PLATFORMTHEME="", QT_STYLE_OVERRIDE="Fusion", QT_QUICK_CONTROLS_STYLE="Basic",
               DBUS_SESSION_BUS_ADDRESS="unix:path=" + str(root / "no-bus"),
               PIPEWIRE_REMOTE="/dev/null", PULSE_SERVER="unix:" + str(root / "no-pulse"))
    code = "import sys,urllib.request; sys.path.insert(0," + repr(str(HERE)) + "); " + \
           "urllib.request.urlopen=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network disabled')); " + \
           "sys.argv=['player','--selftest']; import main; main.main()"
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=40)
    check("complete Player Discover startup on " + face + ": " + result.stdout[-300:] + result.stderr[-500:], result.returncode == 0)
print("PASS discovery")
