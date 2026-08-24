#!/usr/bin/env python3
"""control_player and file_metadata, without touching his music or his screen.

The player half runs against a STUB `playerctl` this test writes ($ORACLE_PLAYERCTL)
— it never reaches the session bus, so the player he is listening to right now
is not paused, skipped or re-shuffled by a test run (root AGENTS.md: "never
drive the running player"). The metadata half runs the REAL executor against
files this test makes in a temp directory.

    oracle-qtenv python3 tools/player-meta-test.py
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

_TMP = Path(tempfile.mkdtemp(prefix="oracle-player-"))

from PySide6.QtCore import QTimer                            # noqa: E402
from PySide6.QtGui import QGuiApplication                    # noqa: E402

sys.argv = [sys.argv[0], "--selftest"]
import main as oracle                                        # noqa: E402

app = QGuiApplication([])
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


# ---- the stub player: records its argv, answers a status line --------------
LOG = _TMP / "calls.log"
STUB = _TMP / "playerctl-stub.sh"
STUB.write_text(
    "#!/bin/sh\n"
    'printf "%s\\n" "$*" >> ' + str(LOG) + "\n"
    'case "$*" in\n'
    '  *nosuch*) echo "No players found" >&2; exit 1 ;;\n'
    '  *metadata*) printf "Playing\\tStone Age\\tMachinedrum\\tPsyconia\\t'
    '236924000\\t61000000\\t0.8\\ttrue\\tPlaylist\\n" ;;\n'
    "esac\n", encoding="utf-8")
STUB.chmod(STUB.stat().st_mode | stat.S_IEXEC)
oracle.PLAYERCTL = str(STUB)

# ---- the stub MIXER: the same, for wpctl ----------------------------------
# It records its argv too, and never touches PipeWire — he is listening while
# this runs, and a test that moves his volume is a bug in the test (root
# AGENTS.md). `main.py` refuses `wpctl` under --selftest unless $ORACLE_WPCTL
# points somewhere, which is the backstop behind this stub.
WLOG = _TMP / "wpctl.log"
WSTUB = _TMP / "wpctl-stub.sh"
WSTUB.write_text(
    "#!/bin/sh\n"
    'printf "%s\\n" "$*" >> ' + str(WLOG) + "\n"
    'case "$1" in\n'
    '  get-volume) echo "Volume: 0.55" ;;\n'
    "esac\n", encoding="utf-8")
WSTUB.chmod(WSTUB.stat().st_mode | stat.S_IEXEC)
os.environ["ORACLE_WPCTL"] = str(WSTUB)
oracle.WPCTL = str(WSTUB)


def wcalls():
    """What the mixer stub was asked to do, and reset."""
    got = WLOG.read_text().splitlines() if WLOG.exists() else []
    if WLOG.exists():
        WLOG.unlink()
    return got

o = oracle.Ollama()
seen = []
o.playerToolDone.connect(lambda j: seen.append(json.loads(j)))


def player(args, ms=6000):
    seen.clear()
    LOG.write_text("", encoding="utf-8")
    o._run_player_tool(args, None, None, None)
    if not seen:
        loop = QTimer()
        loop.setSingleShot(True)
        loop.timeout.connect(app.quit)
        loop.start(ms)
        o.playerToolDone.connect(app.quit)
        app.exec()
        o.playerToolDone.disconnect(app.quit)
    calls = [l for l in LOG.read_text(encoding="utf-8").splitlines() if l]
    return (seen[0] if seen else None), calls


# 1. status: one call, parsed into the shape the model reads
res, calls = player({"action": "status"})
check("status reads the player in one call",
      res is not None and res.get("ok") is True
      and res.get("title") == "Stone Age" and res.get("artist") == "Machinedrum"
      and res.get("playing") == "Playing" and res.get("player_volume") == 80
      and res.get("system_volume") == 55 and res.get("muted") is False
      and res.get("player") == ""
      and res.get("duration_seconds") == 236.9
      and res.get("position_seconds") == 61.0
      and res.get("shuffle") is True and res.get("loop") == "Playlist",
      json.dumps(res)[:200])
check("...and it is a metadata read, nothing else", len(calls) == 1, str(calls))
check("the volume he means is the MACHINE's, read from the mixer every time",
      any(c.startswith("get-volume") for c in wcalls()))

# 2. every verb ends in a status read, so the model reports what it produced
for action, want in (("pause", "pause"), ("play_pause", "play-pause"),
                     ("next", "next"), ("previous", "previous")):
    res, calls = player({"action": action})
    check("%s runs %r then reads back" % (action, want),
          len(calls) == 2 and calls[0].split()[-1] == want
          and res is not None and res.get("did") == action, str(calls))

# 3. seek: absolute and relative are DIFFERENT commands
res, calls = player({"action": "seek", "seconds": 90})
check("an absolute seek is `position 90`",
      calls and calls[0].endswith("position 90"), str(calls))
res, calls = player({"action": "seek", "seconds": 10, "relative": True})
check("a forward relative seek is `position 10+`",
      calls and calls[0].endswith("position 10+"), str(calls))
res, calls = player({"action": "seek", "seconds": -15, "relative": True})
check("a backward relative seek is `position 15-`",
      calls and calls[0].endswith("position 15-"), str(calls))

# 4. VOLUME IS THE SYSTEM'S. His player exposes no MPRIS volume — it answers
# 1.0 for ever — so "turn it down" through playerctl did nothing he could hear
# [his, 2026-08-23]. It goes to the PipeWire mixer instead, and only a
# `scope: player` asks that one app.
wcalls()
res, calls = player({"action": "volume", "level": 40})
w = wcalls()
check("volume 40 sets the SYSTEM volume",
      any(c == "set-volume @DEFAULT_AUDIO_SINK@ 40%" for c in w), str(w))
check("...and the player is only read back, never told to change",
      all("volume" not in c or "metadata" in c for c in calls), str(calls))
res, calls = player({"action": "volume", "level": 500})
check("...an absurd level is clamped, not passed on",
      any(c.endswith("100%") for c in wcalls()), str(w))
res, calls = player({"action": "volume", "level": 40, "scope": "player"})
check("scope=player still drives that one app's own volume",
      calls and calls[0].endswith("volume 0.40"), str(calls))
wcalls()
res, calls = player({"action": "mute"})
check("mute with no argument toggles the machine",
      any(c == "set-mute @DEFAULT_AUDIO_SINK@ toggle" for c in wcalls()))
res, calls = player({"action": "mute", "on": True})
check("...and `on` says which way", any(c.endswith("1") for c in wcalls()))

# 4b. ANY player, not just his. `list` names them and `player:` picks one.
res, calls = player({"action": "list"})
check("list asks the bus, with no -p", calls and calls[0].strip() == "-l",
      str(calls))
res, calls = player({"action": "pause", "player": "vivaldi"})
check("a named player is the one driven",
      calls and calls[0].startswith("-p vivaldi "), str(calls))
res, calls = player({"action": "status"})
check("and with none named it falls back through his player to anything else",
      calls and calls[0].startswith("-p player,%any "), str(calls))

# 5. shuffle and loop
res, calls = player({"action": "shuffle", "on": False})
check("shuffle off", calls and calls[0].endswith("shuffle off"), str(calls))
res, calls = player({"action": "loop", "mode": "track"})
check("loop track", calls and calls[0].endswith("loop track"), str(calls))

# 6. an action the player cannot really do is refused, not silently dropped
res, _ = player({"action": "stop"})
check("an unoffered action is refused with a reason",
      res is not None and "unknown action" in (res.get("error") or ""),
      json.dumps(res)[:120])

# 7. no player: the honest answer, not an empty status
oracle.MPRIS_NAME = "nosuch"
res, _ = player({"action": "status"})
check("no player running is said plainly",
      res is not None and "no music player is running" in (res.get("error") or ""),
      json.dumps(res)[:160])
oracle.MPRIS_NAME = "player"

# ---- the library: browse, then put it on ----------------------------------
# A STUB library script ($ORACLE_MUSIC): the real one reads his 19,000-track
# database and talks to the socket his player is listening on, and a test does
# neither. What is checked here is chatter's half — the request it builds and
# the answer it hands back.
LIB = _TMP / "library-stub.py"
LIB.write_text(
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "req = json.loads(sys.stdin.read() or '{}')\n"
    "open(%r, 'a').write(json.dumps(req) + '\\n')\n"
    "if req.get('op') in ('play', 'queue'):\n"
    "    print(json.dumps({'ok': True, 'sent': len(req.get('paths') or []),\n"
    "                      'queue_length': 3,\n"
    "                      'now_playing': {'title': 'Roygbiv'}}))\n"
    "else:\n"
    "    print(json.dumps({'ok': True, 'count': 1, 'total': 1, 'tracks':\n"
    "        [{'title': 'Roygbiv', 'artist': 'Boards of Canada',\n"
    "          'path': '/aud/boc/01 Roygbiv.flac'}]}))\n"
    % str(_TMP / "lib-calls.log"), encoding="utf-8")
LIB.chmod(LIB.stat().st_mode | stat.S_IEXEC)
os.environ["ORACLE_MUSIC"] = str(LIB)
LIBLOG = _TMP / "lib-calls.log"


def library(args, ms=6000):
    LIBLOG.write_text("", encoding="utf-8")
    remaining = {"n": 1, "sink": [None]}
    o._tool_done = lambda *a, **k: None
    o._run_music_tool(args, 0, remaining, [{}])
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
    sent = [json.loads(l) for l in LIBLOG.read_text(encoding="utf-8").splitlines() if l]
    return (json.loads(sink["content"]) if sink else None), sent


res, sent = library({"action": "search", "query": "boards of canada",
                     "favorites_only": True, "limit": 5})
check("a library search reaches the library with his filters",
      len(sent) == 1 and sent[0]["op"] == "search"
      and sent[0]["q"] == "boards of canada"
      and sent[0]["favorites_only"] is True and sent[0]["limit"] == 5,
      json.dumps(sent)[:200])
check("...and the rows come back with their paths",
      bool(res) and res.get("tracks", [{}])[0].get("path"),
      json.dumps(res)[:160])

res, sent = library({"action": "albums", "artist": "aphex"})
check("albums is its own action", sent and sent[0]["op"] == "albums",
      json.dumps(sent)[:120])


def put_on(args, ms=6000):
    LIBLOG.write_text("", encoding="utf-8")
    seen.clear()
    remaining = {"n": 1, "sink": [None]}
    o._run_player_tool(args, 0, remaining, [{}])
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
    sent = [json.loads(l) for l in LIBLOG.read_text(encoding="utf-8").splitlines() if l]
    return (json.loads(sink["content"]) if sink else None), sent


res, sent = put_on({"action": "play_these",
                    "paths": ["/aud/a.flac", "/aud/b.flac"]})
check("play_these goes to the player's own socket, not MPRIS",
      len(sent) == 1 and sent[0]["op"] == "play"
      and sent[0]["paths"] == ["/aud/a.flac", "/aud/b.flac"],
      json.dumps(sent)[:160])
check("...and answers with what is playing", bool(res) and res.get("ok")
      and res.get("did") == "play_these", json.dumps(res)[:160])
res, sent = put_on({"action": "queue_these", "paths": ["/aud/c.flac"]})
check("queue_these appends", sent and sent[0]["op"] == "queue",
      json.dumps(sent)[:120])
res, _ = put_on({"action": "play_these", "paths": []})
check("nothing to play is refused with a reason",
      bool(res) and "error" in res, json.dumps(res)[:160])

# ---- file_metadata, through the REAL executor ------------------------------
FS = str(APP / "tools" / "sandbox-fs.py")
txt = _TMP / "notes.md"
txt.write_text("one two three\nfour five\n", encoding="utf-8")


def meta(path, **extra):
    req = dict({"op": "meta", "path": str(path).lstrip("/")}, **extra)
    out = subprocess.run([sys.executable, FS, str(_TMP / "sbx"), "/"],
                         input=json.dumps(req).encode(), capture_output=True)
    return json.loads(out.stdout.decode() or "{}")


r = meta(txt)
check("a text file reports its size, type and counts",
      r.get("ok") and r.get("media_type") == "text/plain"
      and r.get("bytes") == 24 and r.get("lines") == 2 and r.get("words") == 5,
      json.dumps(r)[:200])
check("...and a timestamp a model can quote",
      len(str(r.get("modified") or "")) >= 16, str(r.get("modified")))

r = meta(txt, hash=True)
check("the sha256 is opt-in and correct",
      r.get("sha256") == __import__("hashlib").sha256(
          txt.read_bytes()).hexdigest(), str(r.get("sha256"))[:20])
check("...and absent when not asked", "sha256" not in meta(txt))

r = meta(_TMP)
check("a directory says so and counts its entries",
      r.get("kind") == "directory" and r.get("entries", 0) >= 1,
      json.dumps(r)[:160])

# A REAL media file, made here with ffmpeg when it is on this host — the media
# half is the whole reason the tool exists, so it is checked rather than assumed.
clip = _TMP / "tone.flac"
made = subprocess.run(
    ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
     "-metadata", "artist=A Test", "-metadata", "title=A Tone", "-y", str(clip)],
    capture_output=True)
if made.returncode == 0 and clip.exists():
    r = meta(clip)
    check("an audio file reports its container, duration and tags",
          r.get("media_type") == "audio/flac"
          and 1.9 <= (r.get("duration_seconds") or 0) <= 2.1
          and (r.get("tags") or {}).get("artist") == "A Test"
          and any(st.get("type") == "audio" for st in (r.get("streams") or [])),
          json.dumps(r)[:260])
else:
    print("skip  audio metadata (no ffmpeg on this host)")

r = meta("nope/not/here.txt")
check("a missing file is an error, not a crash", "error" in r, json.dumps(r)[:120])

print("\n%d checks failed" % len(fails))
sys.exit(1 if fails else 0)
