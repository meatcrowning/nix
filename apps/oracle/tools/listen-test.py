#!/usr/bin/env python3
"""`listen_audio` and dropped-audio attachments, without hearing his desktop.

Everything here is stubbed or synthetic. The MPRIS half runs against a stub
`playerctl` this test writes ($ORACLE_PLAYERCTL), so the player he is listening
to is never asked anything; the CAPTURE half runs against a stub `ffmpeg`
($ORACLE_FFMPEG), so nothing on this machine's audio output is ever recorded by
a test run (root AGENTS.md: never touch his audio). The file half uses the REAL
executor against wavs this test generates with the `wave` module.

    oracle-qtenv python3 tools/listen-test.py
"""
import base64
import json
import math
import os
import shutil
import stat
import struct
import sys
import tempfile
import wave
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

_TMP = Path(tempfile.mkdtemp(prefix="oracle-listen-"))
os.environ["ORACLE_AUDIO"] = str(_TMP / "clips")

from PySide6.QtCore import QTimer                            # noqa: E402
from PySide6.QtGui import QGuiApplication                    # noqa: E402

sys.argv = [sys.argv[0], "--selftest"]
import main as oracle                                        # noqa: E402

app = QGuiApplication([])
fails = []
HAVE_FFMPEG = bool(shutil.which("ffmpeg"))


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


def tone(path, seconds=5.0, rate=44100, channels=2):
    """A real wav file, made without ffmpeg so the fixtures cost nothing."""
    n = int(seconds * rate)
    frames = bytearray()
    for i in range(n):
        v = int(12000 * math.sin(2 * math.pi * 440 * i / rate))
        frames += struct.pack("<h", v) * channels
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return str(path)


def wav_facts(raw):
    """(rate, channels, seconds) of a wav in memory."""
    p = _TMP / "read-back.wav"
    p.write_bytes(raw)
    with wave.open(str(p), "rb") as w:
        return w.getframerate(), w.getnchannels(), round(
            w.getnframes() / float(w.getframerate()), 1)


SONG = tone(_TMP / "song.wav", 5.0)
PICTURE = _TMP / "not-audio.png"
PICTURE.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
NOTES = _TMP / "notes.txt"
NOTES.write_text("just text\n", encoding="utf-8")

# ---- 1. what IS audio: magic bytes, never the extension -------------------
check("a wav is heard as audio", oracle.Ollama._sniff_audio(SONG) == "audio/wav")
FAKE = _TMP / "song.flac"          # a png wearing a .flac name
shutil.copy(PICTURE, FAKE)
check("an extension is a claim, not a fact",
      oracle.Ollama._sniff_audio(str(FAKE)) == "",
      oracle.Ollama._sniff_audio(str(FAKE)))
check("a png is not audio", oracle.Ollama._sniff_audio(str(PICTURE)) == "")
check("a text file is not audio", oracle.Ollama._sniff_audio(str(NOTES)) == "")
for head, want in ((b"fLaC\0\0\0\0", "audio/flac"), (b"ID3\x03\0\0\0", "audio/mpeg"),
                   (b"OggS\0\x02\0\0", "audio/ogg"), (b"\xff\xfb\x90\x44", "audio/mpeg")):
    f = _TMP / ("m-" + want.replace("/", "-"))
    f.write_bytes(head + b"\0" * 24)
    check("magic %r reads as %s" % (head[:4], want),
          oracle.Ollama._sniff_audio(str(f)) == want)

# ---- 2. a dropped file is TRIMMED and downmixed, or honestly refused ------
items = [{"name": "song.wav", "path": SONG}]
b64, note = oracle.Ollama._read_audio_attachments(items, audible=False)
check("a model with no ear is sent no bytes", b64 == [])
check("...and the note says so, and names the path",
      "no audio support" in note and SONG in note, note[:120])

if HAVE_FFMPEG:
    b64, note = oracle.Ollama._read_audio_attachments(items, audible=True)
    check("an audio model gets one clip", len(b64) == 1)
    rate, ch, secs = wav_facts(base64.b64decode(b64[0]))
    check("...at 16 kHz mono, whatever the source was",
          rate == oracle.AUDIO_RATE and ch == 1, "%d Hz x%d" % (rate, ch))
    check("...and the note names the file for the other tools", SONG in note)
    long_wav = tone(_TMP / "long.wav", 3.0)
    wav, err = oracle.Ollama._audio_excerpt(long_wav, 1.0, 1.0)
    check("an excerpt is the window asked for, not the file",
          not err and abs(wav_facts(wav)[2] - 1.0) < 0.2, err or str(wav_facts(wav)))
    wav, err = oracle.Ollama._audio_excerpt(str(NOTES), 0, 5)
    check("a file with no sound in it fails with a reason", not wav and err, err)

# ---- 3. the executor op: the trim happens where the FILE is ---------------
def fs(req):
    import subprocess
    out = subprocess.run([sys.executable, str(HERE / "sandbox-fs.py"), "/", "/"],
                         input=json.dumps(req).encode(), capture_output=True)
    return json.loads(out.stdout.decode("utf-8", "replace") or "{}")

if HAVE_FFMPEG:
    r = fs({"op": "audio", "path": SONG, "start": 1, "seconds": 2})
    check("op audio hands back a bounded wav",
          r.get("ok") and r.get("media") == "audio/wav"
          and abs(r.get("seconds", 0) - 2.0) < 0.3 and r.get("start") == 1.0,
          json.dumps({k: v for k, v in r.items() if k != "b64"})[:160])
    check("...and reports the whole file's length beside it",
          abs(r.get("duration", 0) - 5.0) < 0.2, str(r.get("duration")))
    check("...at 16 kHz mono",
          wav_facts(base64.b64decode(r["b64"]))[:2] == (oracle.AUDIO_RATE, 1))
    r = fs({"op": "audio", "path": SONG, "start": 99, "seconds": 5})
    check("a start past the end is a reason, not a silent clip",
          "only 5.0s long" in (r.get("error") or ""), json.dumps(r)[:140])
    r = fs({"op": "audio", "path": str(NOTES)})
    check("a text file is refused", "error" in r, json.dumps(r)[:120])
r = fs({"op": "audio", "path": "/etc/shadow"})
check("the read jail still applies", "error" in r, json.dumps(r)[:100])

# ---- 4. the tool itself ---------------------------------------------------
oracle.TOOLS_HOST = oracle.LOCAL_HOST      # never ssh from a test
o = oracle.Ollama()
o._model = o._ctx_model = "gemma4-test"

LOG = _TMP / "playerctl.log"
STUB = _TMP / "playerctl-stub.sh"
STUB.write_text(
    "#!/bin/sh\n"
    'printf "%s\\n" "$*" >> ' + str(LOG) + "\n"
    'case "$PCTL_MODE" in\n'
    '  stream) printf "https://stream.example/live\\t0\\tSomebody - Live\\n" ;;\n'
    '  none) echo "No players found" >&2; exit 1 ;;\n'
    '  *) printf "file://' + SONG + '\\t3000000\\tAn Artist - A Track\\n" ;;\n'
    "esac\n", encoding="utf-8")
STUB.chmod(STUB.stat().st_mode | stat.S_IEXEC)
oracle.PLAYERCTL = str(STUB)

FF = _TMP / "ffmpeg-stub.sh"
FFLOG = _TMP / "ffmpeg.log"
FF.write_text(
    "#!/bin/sh\n"
    'printf "%s\\n" "$*" >> ' + str(FFLOG) + "\n"
    "cat " + str(_TMP / "capture-fixture.wav") + "\n", encoding="utf-8")
FF.chmod(FF.stat().st_mode | stat.S_IEXEC)
tone(_TMP / "capture-fixture.wav", 2.0, oracle.AUDIO_RATE, 1)


def listen(args, ms=20000):
    """One listen_audio call, answered into a fake tool sink."""
    o._pending_audio = []
    for f in (LOG, FFLOG):
        f.write_text("", encoding="utf-8")
    box = {"n": 1, "sink": [None]}
    done = {"n": False}
    real = o._tool_done

    def stop(remaining, calls):
        done["n"] = True
        app.quit()

    o._tool_done = stop
    o._listen_audio(args, 0, box, None)
    if not done["n"]:
        t = QTimer()
        t.setSingleShot(True)
        t.timeout.connect(app.quit)
        t.start(ms)
        app.exec()
    o._tool_done = real
    res = json.loads(box["sink"][0]["content"]) if box["sink"][0] else None
    calls = [l for l in LOG.read_text(encoding="utf-8").splitlines() if l]
    ffcalls = [l for l in FFLOG.read_text(encoding="utf-8").splitlines() if l]
    return res, calls, ffcalls


# a model with no ear is refused BEFORE anything is read
o._caps = ["vision", "tools"]
res, calls, _ = listen({"source": "now_playing"})
check("a model with no audio capability is refused with a reason",
      res and "no audio support" in (res.get("error") or ""), json.dumps(res)[:140])
check("...and the player was never asked anything", calls == [], str(calls))

o._caps = ["vision", "audio", "tools"]
if HAVE_FFMPEG:
    res, calls, _ = listen({"source": "now_playing"})
    check("now_playing finds the track through MPRIS and cuts it",
          res and res.get("ok") and res.get("source") == "now_playing",
          json.dumps(res)[:200] if res else "none")
    check("...starting a couple of seconds before where he is",
          res and abs(res.get("start_seconds", 0) - 1.0) < 0.01,
          str(res.get("start_seconds") if res else None))
    verbs = calls[0].split("--format")[0].split() if calls else []
    check("...by READING the bus, never driving it",
          len(calls) == 1 and "metadata" in verbs
          and not ({"play", "play-pause", "pause", "next", "previous",
                    "position", "volume", "shuffle", "loop"} & set(verbs)),
          str(calls))
    check("...the model is handed bytes, and the transcript is not",
          len(o._pending_audio) == 1 and "b64" not in (res or {}))
    clip = (res or {}).get("clip", "")
    check("...and the clip he can play back is kept and named",
          clip and os.path.exists(clip) and str(_TMP) in clip, clip)

    res, _, _ = listen({"source": "file", "path": SONG, "start": 2,
                        "seconds": 1})
    check("a named file is excerpted where asked",
          res and res.get("ok") and res.get("start_seconds") == 2.0
          and abs(res.get("seconds", 0) - 1.0) < 0.3, json.dumps(res)[:160])
    res, _, _ = listen({"source": "file", "path": SONG, "seconds": 9999})
    check("an absurd length is clamped, not passed on",
          res and res.get("seconds", 0) <= oracle.LISTEN_MAX_SECONDS,
          str(res.get("seconds") if res else None))

res, _, _ = listen({"source": "file"})
check("file with no path says what to do instead",
      res and "no path given" in (res.get("error") or ""), json.dumps(res)[:140])

os.environ["PCTL_MODE"] = "stream"
res, _, _ = listen({"source": "now_playing"})
check("a stream that is not a file points at capture, not a bad path",
      res and "capture" in (res.get("error") or ""), json.dumps(res)[:160])
os.environ["PCTL_MODE"] = "none"
res, _, _ = listen({"source": "now_playing"})
check("nothing playing is said plainly", res and res.get("error"),
      json.dumps(res)[:160])
os.environ.pop("PCTL_MODE", None)

# capture: the stub proves WHAT would be recorded without recording anything
oracle.FFMPEG = str(FF)
res, _, ffcalls = listen({"source": "capture", "seconds": 5})
check("capture delivers what the speakers are putting out",
      res and res.get("ok") and res.get("source") == "capture",
      json.dumps(res)[:160] if res else "none")
check("...from the sink MONITOR, never a microphone",
      ffcalls and "@DEFAULT_MONITOR@" in ffcalls[0], str(ffcalls))
check("...bounded, so nothing can leave a recorder running",
      ffcalls and "-t 5.000" in ffcalls[0], str(ffcalls))
res, _, ffcalls = listen({"source": "capture", "seconds": 9999})
check("...and an absurd capture is clamped to the ceiling",
      ffcalls and ("-t %.3f" % oracle.LISTEN_CAPTURE_MAX) in ffcalls[0],
      str(ffcalls))

# ---- 5. the schema is offered by CAPABILITY -------------------------------
def offered():
    return [t["function"]["name"] for t in o._offered_tools()]

o._caps = ["vision", "audio", "tools"]
check("an audio model carries the tool on the wire", "listen_audio" in offered())
o._caps = ["vision", "tools"]
check("a deaf one does not", "listen_audio" not in offered())
check("...but it is still in the index every model reads",
      "listen_audio" in oracle.tools_note())
# It stays with the MAIN agent, like view_image: the clip rides a message on
# the loop that called it, and a subagent's loop ends before that is sent.
check("a subagent is not given it", "listen_audio" not in oracle._tool_registry())
check("...and get_tools can still attach it by group",
      "listen_audio" in oracle.EXTRA_TOOL_GROUPS["audio"])

if not HAVE_FFMPEG:
    print("note ffmpeg is absent here — the trimming checks were skipped")
shutil.rmtree(_TMP, ignore_errors=True)
print(("FAILED: " + ", ".join(fails)) if fails else "all listen checks passed")
sys.exit(1 if fails else 0)
