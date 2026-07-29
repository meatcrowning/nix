#!/usr/bin/env python3
"""Regression test for atomicsave.py — the module both tag-write paths go
through before they touch a library file.

It proves four things, on COPIES only (it never opens a library file for
writing, and refuses to run against a directory under the real library):

  1. the audio STREAM is byte-identical after a tag write, per format. Hashed
     as `ffmpeg -i F -map 0:a -f s16le - | md5sum` — plain `ffmpeg -f md5 -` is
     nondeterministic on files with embedded cover art and has raised false
     alarms here before (player/AGENTS.md).
  2. the tags round-trip: write, re-read, same value.
  3. every failure mode leaves the ORIGINAL byte-for-byte intact and no temp
     file behind — disk-full (simulated by a free-space check that cannot
     pass), a missing file, an unwritable directory, a file mutagen cannot
     open, and a mutate() that raises halfway.
  4. os.replace() over an existing file behaves on exFAT: the target is never
     absent, and a reader either sees all of the old bytes or all of the new.

    tools/atomic-write-test.py --samples DIR    # DIR holds sample.{mp3,flac,...}
    tools/atomic-write-test.py --samples DIR --exfat-probe /run/media/lam/SSD/.probe
"""
import argparse
import errno
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent / "pylib"))

import atomicsave  # noqa: E402
import lyrics as L  # noqa: E402
import mutagen  # noqa: E402

LIB = "/run/media/lam/SSD/aud"
FAILS = []
OKS = 0


def check(name, cond, detail=""):
    global OKS
    if cond:
        OKS += 1
        print("  ok   %s %s" % (name, detail))
    else:
        FAILS.append(name)
        print("  FAIL %s %s" % (name, detail))


def audio_md5(path):
    """Hash the decoded audio stream only. Container/tag/cover-art bytes are
    excluded by construction, which is the whole point."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path),
                        "-map", "0:a", "-f", "s16le", "-"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed on %s: %s" % (path, p.stderr[-400:]))
    return hashlib.md5(p.stdout).hexdigest()


def file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_back(path):
    """(rating, favorite, playcount, lyrics) as this app would read them."""
    a = mutagen.File(path)
    out = {}
    for k in ("FMPS_Rating", "FAVORITE", "FMPS_Playcount"):
        v = None
        for cand in ("TXXX:" + k, "----:com.apple.iTunes:" + k,
                     k.upper(), k):
            try:
                got = a.tags.get(cand) if a.tags is not None else None
            except Exception:
                got = None
            if got:
                v = got[0]
                if isinstance(v, bytes):
                    v = v.decode()
                v = str(v)
                break
        out[k] = v
    out["lyrics"], out["synced"] = L.read_embedded(path)   # (text|None, synced)
    return out


def rating_entry(rating, favorite, plays):
    return {"rating": rating, "favorite": favorite, "play_count": plays}


def apply_rating(audio, entry):
    """The same mutation TagWriter._apply performs, without importing main.py
    (which pulls in PySide6, libmpv and an MPRIS bus)."""
    from mutagen.id3 import ID3, TXXX
    from mutagen.mp4 import MP4, MP4FreeForm
    from mutagen.flac import FLAC
    rating, favorite, plays = entry["rating"], entry["favorite"], entry["play_count"]
    tags = audio.tags
    if isinstance(tags, ID3) or (tags is None and hasattr(audio, "add_tags")
                                 and not isinstance(audio, (MP4, FLAC))):
        if tags is None:
            audio.add_tags()
            tags = audio.tags
        for desc, val in (("FMPS_Rating", rating), ("FAVORITE", favorite),
                          ("FMPS_Playcount", plays)):
            if val == "keep":
                continue
            tags.setall("TXXX:" + desc,
                        [TXXX(encoding=3, desc=desc, text=[str(val)])])
    elif isinstance(audio, MP4):
        for name, val in (("FMPS_Rating", rating), ("FAVORITE", favorite),
                          ("FMPS_Playcount", plays)):
            if val == "keep":
                continue
            audio["----:com.apple.iTunes:" + name] = [MP4FreeForm(str(val).encode())]
    else:
        for key, val in (("FMPS_RATING", rating), ("FAVORITE", favorite),
                         ("FMPS_PLAYCOUNT", plays)):
            if val == "keep":
                continue
            audio[key] = [str(val)]


LRC = "\n".join("[00:%02d.%02d] line %d of a synced lyric that is long enough "
                "to outgrow any tag padding this file has" % (i, i, i)
                for i in range(60))


def test_format(path):
    print("\n== %s (%.1f MB)" % (path.name, path.stat().st_size / 1e6))
    before_audio = audio_md5(path)
    before_stat = path.stat()

    atomicsave.atomic_save(path, lambda a: apply_rating(a, rating_entry(0.8, "1", 7)))
    check("%s audio-identical after rating" % path.suffix,
          audio_md5(path) == before_audio, before_audio[:12])
    got = read_back(path)
    check("%s rating round-trip" % path.suffix,
          got["FMPS_Rating"] == "0.8" and got["FAVORITE"] == "1"
          and got["FMPS_Playcount"] == "7", str(got)[:120])

    L.write_embedded(path, LRC)
    check("%s audio-identical after lyrics" % path.suffix,
          audio_md5(path) == before_audio)
    got = read_back(path)
    check("%s lyrics round-trip" % path.suffix,
          (got["lyrics"] or "").strip() == LRC.strip() and got["synced"],
          "%d chars, synced=%s" % (len(got["lyrics"] or ""), got["synced"]))
    check("%s earlier rating survived the lyrics write" % path.suffix,
          got["FMPS_Rating"] == "0.8")

    check("%s mtime preserved" % path.suffix,
          abs(path.stat().st_mtime - before_stat.st_mtime) < 0.01,
          "%r -> %r" % (before_stat.st_mtime, path.stat().st_mtime))
    check("%s no temp files left" % path.suffix,
          not [n for n in os.listdir(path.parent)
               if n.startswith(atomicsave.TMP_PREFIX)])


def test_failures(sample):
    print("\n== failure paths")
    d = Path(tempfile.mkdtemp(prefix="atomic-fail-"))
    try:
        f = d / ("victim" + sample.suffix)
        shutil.copyfile(sample, f)
        pristine = file_md5(f)

        def intact(label):
            check(label + ": original intact", file_md5(f) == pristine)
            check(label + ": no temp litter",
                  not [n for n in os.listdir(d)
                       if n.startswith(atomicsave.TMP_PREFIX)])

        # 1. disk full — an impossible free-space requirement
        old = atomicsave.GROWTH_SLACK
        atomicsave.GROWTH_SLACK = 1 << 60
        try:
            atomicsave.atomic_save(f, lambda a: apply_rating(a, rating_entry(1.0, "1", 1)))
            check("no-space raises", False, "no exception")
        except atomicsave.NoSpace as e:
            check("no-space raises NoSpace", e.errno == errno.ENOSPC, str(e)[:70])
        finally:
            atomicsave.GROWTH_SLACK = old
        intact("no-space")

        # 2. missing file
        try:
            atomicsave.atomic_save(d / "nope.mp3", lambda a: None)
            check("missing file raises", False)
        except FileNotFoundError:
            check("missing file raises FileNotFoundError", True)

        # 3. mutagen cannot open it
        junk = d / "junk.mp3"
        junk.write_bytes(b"not audio at all" * 100)
        try:
            atomicsave.atomic_save(junk, lambda a: None)
            check("unparseable raises", False)
        except Exception as e:
            check("unparseable raises", "could not open" in str(e)
                  or isinstance(e, mutagen.MutagenError), type(e).__name__)
        check("unparseable: no temp litter",
              not [n for n in os.listdir(d) if n.startswith(atomicsave.TMP_PREFIX)])

        # 4. mutate() raises mid-write
        try:
            atomicsave.atomic_save(f, lambda a: (_ for _ in ()).throw(ValueError("boom")))
            check("mutate raising propagates", False)
        except ValueError:
            check("mutate raising propagates", True)
        intact("mutate-raises")

        # 5. unwritable directory
        ro = d / "ro"
        ro.mkdir()
        g = ro / ("victim" + sample.suffix)
        shutil.copyfile(sample, g)
        g_md5 = file_md5(g)
        os.chmod(ro, 0o555)
        try:
            atomicsave.atomic_save(g, lambda a: apply_rating(a, rating_entry(1.0, "1", 1)))
            check("read-only dir raises", False)
        except OSError as e:
            check("read-only dir raises OSError", True, e.__class__.__name__)
        finally:
            os.chmod(ro, 0o755)
        check("read-only dir: original intact", file_md5(g) == g_md5)
        check("read-only dir: no temp litter",
              not [n for n in os.listdir(ro) if n.startswith(atomicsave.TMP_PREFIX)])

        # 6. orphan sweep
        stale = d / (atomicsave.TMP_PREFIX + "stale.mp3")
        stale.write_bytes(b"x")
        os.utime(stale, (0, 0))
        fresh = d / (atomicsave.TMP_PREFIX + "fresh.mp3")
        fresh.write_bytes(b"x")
        atomicsave.sweep_orphans(d)
        check("sweep removes stale temp", not stale.exists())
        check("sweep keeps a temp younger than an hour", fresh.exists())
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_replace_semantics(probe_dir):
    """os.replace() over an existing file, hammered by a concurrent reader.
    On any filesystem where this is a real rename the reader must see either
    the old content whole or the new content whole, and never ENOENT."""
    print("\n== os.replace() on %s" % probe_dir)
    d = Path(probe_dir)
    d.mkdir(parents=True, exist_ok=True)
    target = d / "target.bin"
    old, new = b"O" * (1 << 20), b"N" * (1 << 20)
    target.write_bytes(old)
    seen, missing, torn = set(), [0], [0]
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                b = target.read_bytes()
            except FileNotFoundError:
                missing[0] += 1
                continue
            if b == old:
                seen.add("old")
            elif b == new:
                seen.add("new")
            else:
                torn[0] += 1

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    for i in range(60):
        tmp = d / ("%stmp%d.bin" % (atomicsave.TMP_PREFIX, i))
        tmp.write_bytes(new if i % 2 == 0 else old)
        os.replace(tmp, target)
        time.sleep(0.002)
    stop.set()
    t.join()
    check("replace: reader never saw a torn file", torn[0] == 0, "torn=%d" % torn[0])
    check("replace: target never vanished", missing[0] == 0, "enoent=%d" % missing[0])
    check("replace: reader saw both whole versions", seen == {"old", "new"}, str(seen))
    check("replace: no temp left", not [n for n in os.listdir(d)
                                        if n.startswith(atomicsave.TMP_PREFIX)])
    target.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True,
                    help="directory of sample.{mp3,flac,m4a,dsf,wav} COPIES")
    ap.add_argument("--exfat-probe", help="scratch dir on the exFAT volume")
    a = ap.parse_args()
    samples = Path(a.samples).resolve()
    if str(samples).startswith(LIB):
        sys.exit("refusing to run inside the real library (%s)" % LIB)

    files = sorted(p for p in samples.iterdir() if p.name.startswith("sample."))
    if not files:
        sys.exit("no sample.* files in %s" % samples)
    for f in files:
        test_format(f)
    test_failures(files[0])
    if a.exfat_probe:
        if a.exfat_probe.startswith(LIB):
            sys.exit("refusing to probe inside the real library")
        test_replace_semantics(a.exfat_probe)

    print("\n%d checks passed, %d failed" % (OKS, len(FAILS)))
    for f in FAILS:
        print("  FAILED:", f)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
