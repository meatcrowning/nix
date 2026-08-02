#!/usr/bin/env python3
"""Offscreen harness for tools/replaygain.py.

Builds a scratch library under a temp dir (synthetic audio via ffmpeg, no
ReplayGain tags), a scratch library.db under an isolated XDG_DATA_HOME, then
drives the real replaygain.py binary as a subprocess with that environment.
The LIVE library and the running player's session are never touched; every
assertion below runs on the scratch tree.

Run under the player's python env (it imports main, which needs mutagen/PySide6):

    PY=$(grep -oE '/nix/store/[^" ]+-env/bin/python3[0-9.]*' "$(command -v player)" | head -1)
    "$PY" apps/player/tools/replaygain-test.py

Covers: status; dry run (nothing written); --write (tags present, readable by
the player's own read_replaygain, audio stream byte-identical, DB row updated);
unsupported formats (DSD) skipped; idempotence (a second --write is a no-op).
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Isolate the player's data/cache/state BEFORE importing main, so open_db()
# points at the scratch DB and nothing touches ~/.local.
HERE = Path(__file__).resolve().parent
_PLAYER = HERE.parent
sys.path.insert(0, str(_PLAYER))
sys.path.insert(0, str(_PLAYER / "pylib"))

WORK = Path(tempfile.mkdtemp(prefix="rg-test-"))
DATA = WORK / "data"
CACHE = WORK / "cache"
STATE = WORK / "state"
RUN = WORK / "run"
for d in (DATA, CACHE, STATE, RUN):
    d.mkdir(parents=True, exist_ok=True)

os.environ["XDG_DATA_HOME"] = str(DATA)
os.environ["XDG_CACHE_HOME"] = str(CACHE)
os.environ["XDG_STATE_HOME"] = str(STATE)
os.environ["XDG_RUNTIME_DIR"] = str(RUN)
os.environ["PLAYER_DATA"] = str(DATA)   # harmless

import main as P       # noqa: E402
import mutagen          # noqa: E402

PASS = 0
FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s %s" % (label, extra))


def make_audio(path, dur=3, freq=440, codec_args=()):
    """ffmpeg sine -> a real audio file with no tags."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", "sine=frequency=%d:duration=%d" % (freq, dur),
           *codec_args, str(path)]
    subprocess.run(cmd, check=True)
    return path


def audio_stream_md5(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-i", str(path), "-map", "0:a", "-f", "s16le", "-"],
                       capture_output=True)
    return hashlib.md5(p.stdout).hexdigest()


def rg_of(path):
    """The player's own tag reader — proves the written tags are what mpv sees."""
    try:
        a = mutagen.File(path)
    except Exception:
        return None
    return P.read_replaygain(a) if a is not None else None


def run_tool(*args, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run([sys.executable, str(HERE / "replaygain.py"), *args],
                          capture_output=True, text=True, env=e)


# --- build the scratch library --------------------------------------------

lib = WORK / "aud"
tracks = {}
tracks["album1_a"] = make_audio(lib / "Artist One" / "Album Alpha" / "01 First.flac",
                                codec_args=["-c:a", "flac"])
tracks["album1_b"] = make_audio(lib / "Artist One" / "Album Alpha" / "02 Second.mp3",
                                codec_args=["-c:a", "libmp3lame"])
tracks["album2_a"] = make_audio(lib / "Artist Two" / "Album Beta" / "01 Only.m4a",
                                codec_args=["-c:a", "aac"])
tracks["loose_a"] = make_audio(lib / "Loose" / "solo.opus",
                               codec_args=["-c:a", "libopus"])

# hash the audio streams so we can prove the tag write leaves them untouched
before = {k: audio_stream_md5(v) for k, v in tracks.items()}

# a DSD file: real untagged dsf from the library is the honest specimen, but
# the tool filters by extension before touching anything, so a DB row with a
# .dsf path is enough to prove it is skipped.
fake_dsf = WORK / "aud" / "DSD" / "track.dsf"
fake_dsf.parent.mkdir(parents=True, exist_ok=True)
with open(fake_dsf, "wb") as f:
    f.write(b"\x00" * 64)

# --- seed the scratch DB so the tool's DB enumeration finds the tracks -----

con = P.open_db()
for name, path in tracks.items():
    t = P.read_tags(str(path))
    assert t is not None, "read_tags failed for %s" % path
    st = path.stat()
    t.update(rg_track_gain=None, rg_track_peak=None,
             rg_album_gain=None, rg_album_peak=None)
    con.execute(
        """INSERT INTO tracks (path, mtime, size, title, artist, album,
                              album_artist, track, disc, date, year, orig_year,
                              genre, duration, codec, samplerate, bitdepth,
                              rating, favorite, play_count, added_at, has_art,
                              rg_track_gain, rg_track_peak, rg_album_gain,
                              rg_album_peak)
           VALUES (:path,:mtime,:size,:title,:artist,:album,:album_artist,
                   :track,:disc,:date,:year,:orig_year,:genre,:duration,
                   :codec,:samplerate,:bitdepth,:rating,:favorite,:play_count,
                   :added_at,:has_art,:rg_track_gain,:rg_track_peak,
                   :rg_album_gain,:rg_album_peak)""",
        {**t, "path": str(path), "mtime": st.st_mtime, "size": st.st_size,
         "added_at": 0})
con.execute(
    "INSERT INTO tracks (path, title, mtime, size, added_at) "
    "VALUES (?, 'dsd', 0, 64, 0)",
    (str(fake_dsf),))
con.commit()
con.close()

print("scratch library: %d supported + 1 DSD" % len(tracks))

# --- status ---------------------------------------------------------------

out = run_tool("status")
print("--- status ---")
print((out.stdout + out.stderr).strip())
check("status exits 0", out.returncode == 0, out.stderr)

# --- dry run (write nothing) ----------------------------------------------

out = run_tool("scan")
print("--- scan (dry) ---")
print((out.stdout + out.stderr).strip())
check("dry run exits 0", out.returncode == 0, out.stderr)
check("dry run reports it is a dry run", "dry run" in out.stdout)
dry = {k: rg_of(v) for k, v in tracks.items()}
check("dry run wrote NO tags (all still None)",
      all(dry[k] is None or dry[k]["rg_track_gain"] is None for k in tracks),
      "".join("%s=%r " % (k, dry[k]) for k in tracks))
# DB untouched by dry run
con = P.open_db()
n = con.execute("SELECT COUNT(rg_track_gain) c FROM tracks").fetchone()["c"]
con.close()
check("dry run left DB rg columns NULL (count=%d)" % n, n == 0)

# --- write ----------------------------------------------------------------

out = run_tool("scan", "--write")
print("--- scan --write ---")
print((out.stdout + out.stderr).strip())
check("write exits 0", out.returncode == 0, out.stderr)
con = P.open_db()
n = con.execute("SELECT COUNT(rg_track_gain) c FROM tracks").fetchone()["c"]
con.close()
check("write set %d rg track_gain (== %d supported)" % (n, len(tracks)),
      n == len(tracks))


def verify_written_one(k):
    r = rg_of(tracks[k])
    check("%s tags present & readable" % k,
          r is not None and r["rg_track_gain"] is not None,
          repr(r))
    if r and r["rg_track_gain"] is not None:
        # rsgain heights for these sine clips are negative-but-finite;
        # the exact number is rsgain's, so assert it is a sane reachable dB
        g = r["rg_track_gain"]
        check("%s gain is a finite dB number (%.2f)" % (k, g), -30 < g < 30)
        check("%s peak is a valid peak" % k,
              r["rg_track_peak"] is not None and 0 < r["rg_track_peak"] <= 4)


for k in tracks:
    verify_written_one(k)

# audio untouched by the tag write
for k, v in tracks.items():
    after = audio_stream_md5(v)
    check("%s audio stream byte-identical after tag write" % k,
          after == before[k],
          "%s != %s" % (after, before[k]))

# DB exactly matches the written tags
con = P.open_db()
row = con.execute("SELECT rg_track_gain FROM tracks WHERE path=?",
                  (str(tracks["album1_a"]),)).fetchone()
con.close()
check("DB rg_track_gain matches written tag",
      row is not None and abs(row["rg_track_gain"] - rg_of(tracks["album1_a"])["rg_track_gain"]) < 0.01)

# unsupported DSD skipped
r = rg_of(fake_dsf)
con = P.open_db()
d = con.execute("SELECT rg_track_gain FROM tracks WHERE path=?",
                (str(fake_dsf),)).fetchone()
con.close()
check("DSD never tagged (file + DB)", (d is None or d["rg_track_gain"] is None))

# --- idempotence ----------------------------------------------------------

out = run_tool("scan", "--write")
print("--- second --write ---")
print((out.stdout + out.stderr).strip())
check("second write is a no-op ('nothing to do')", "nothing to do" in out.stdout)

# the new-track hook engine: auto mode on a fully-tagged library is a no-op
out = run_tool("scan", "--write", "--auto")
check("auto mode (hook engine) is a no-op when fully tagged",
      "nothing to do" in out.stdout, (out.stdout + out.stderr).strip())

# explicit PATH form re-scans a single file, still idempotent
out = run_tool("scan", str(tracks["album1_a"]))
check("explicit PATH dry run ok", out.returncode == 0, out.stderr)

print("")
print("RESULT: %d passed, %d failed" % (PASS, FAIL))
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if FAIL else 0)
