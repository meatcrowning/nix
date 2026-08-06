#!/usr/bin/env python3
"""Offscreen harness for filer's preview thumbnails — the VIDEO half especially.

Covers the pipeline end to end without a window: `preview_kind`'s classification,
`make_thumb` producing a real poster frame for a video through ffmpeg, the
freedesktop shared cache being written and re-read (so the second visit is a file
read, not another ffmpeg), the failure marker for a file that only *looks* like a
video, the oversized-source guard applying to stills but NOT to video, and the
grid actually taking video entries in the real `Main.qml`.

Every clip it thumbnails is generated here with ffmpeg, so the run touches none
of the user's own media and none of his thumbnail cache entries.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

FILER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FILER)
sys.path.insert(0, os.path.join(os.path.dirname(FILER), "pylib"))

from PySide6.QtGui import QGuiApplication  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def make_clip(path, black=1, colour=5, size="160x120", codec="libvpx-vp9"):
    """A real clip, generated: `black` seconds of black followed by `colour`
    seconds of a flat blue. The lead-in is the point — a thumbnailer that grabs
    frame 0, or that seeks somewhere still inside the black, comes back with a
    black tile, and the checks below can tell the difference."""
    import main as m
    r = subprocess.run(
        [m.tool("ffmpeg"), "-v", "error", "-y",
         "-f", "lavfi", "-i", "color=c=black:s=%s:d=%d" % (size, black),
         "-f", "lavfi", "-i", "color=c=0x2080ff:s=%s:d=%d" % (size, colour),
         # a gradient over the blue so the frame is not itself a flat field
         "-filter_complex",
         "[1:v]geq=r='X*255/W':g=128:b='Y*255/H'[c];[0:v][c]concat=n=2:v=1:a=0[v]",
         "-map", "[v]", "-c:v", codec, "-pix_fmt", "yuv420p", path],
        capture_output=True, timeout=180)
    return r.returncode == 0 and os.path.exists(path)


def write_png(path, w=8, h=8):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + b"\xa0\x40\x80" * w for _ in range(h))
    open(path, "wb").write(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b""))


def forget(m, path):
    """Drop every cache entry for `path`, so the next make_thumb generates.
    Only ever touches hashes of files this harness created."""
    h = m._thumb_hash(path)
    for p in (m.THUMB_ROOT / "large" / (h + ".png"),
              m.THUMB_ROOT / "normal" / (h + ".png"),
              m._fail_path(path)):
        try:
            p.unlink()
        except OSError:
            pass


def main():
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on platform %r, not offscreen" % app.platformName())
    import main as m

    # ---- 1. classification ---------------------------------------------------
    for name, want in (("a.webm", "video"), ("a.mp4", "video"), ("a.mkv", "video"),
                       ("a.mov", "video"), ("a.m2ts", "video"), ("a.png", "image"),
                       ("a.jxl", "image"), ("a.txt", "file"), ("a.WEBM", "video")):
        check("preview_kind(%s) == %s" % (name, want),
              m.preview_kind(name, False) == want, m.preview_kind(name, False))
    check("a directory is never previewable", m.preview_kind("clips.mp4", True) == "dir")
    # filer's video set has to be viewer's, or a file gets a tile here and no
    # player there.
    check("filer's VIDEO_EXTS matches viewer's",
          m.VIDEO_EXTS == _viewer_video_exts(), sorted(m.VIDEO_EXTS))

    tmp = tempfile.mkdtemp(prefix="filer-thumb-")
    try:
        if not shutil.which(m.tool("ffmpeg")) and not os.path.exists(m.tool("ffmpeg")):
            check("ffmpeg is available", False, "no ffmpeg on PATH — cannot test video")
            return 1

        # ---- 2. a real poster frame, and the seek that finds it --------------
        webm = os.path.join(tmp, "clip.webm")
        check("built a test .webm", make_clip(webm))
        forget(m, webm)
        t0 = time.time()
        img = m.make_thumb(webm)
        cold = time.time() - t0
        check("a webm gets a thumbnail", not img.isNull() and img.width() > 0,
              "%dx%d" % (img.width(), img.height()))
        check("the thumbnail is bounded to THUMB_MAX",
              max(img.width(), img.height()) <= m.THUMB_MAX,
              "%dx%d" % (img.width(), img.height()))
        check("the poster frame is seeked past the black lead-in, not frame 0",
              not m._is_blank(img),
              img.pixelColor(img.width() // 2, img.height() // 2).name())

        # A clip black for well past the FIRST seek fraction: the blank check
        # has to fall through to a later one rather than tile it black.
        lead = os.path.join(tmp, "leadin.webm")
        check("built a clip with a long black lead-in", make_clip(lead, black=4, colour=4))
        forget(m, lead)
        limg = m.make_thumb(lead)
        check("a blank first pick falls through to a later seek",
              not limg.isNull() and not m._is_blank(limg),
              limg.pixelColor(limg.width() // 2, limg.height() // 2).name())

        # ...and a clip that really is blank throughout still gets a tile: a
        # blank frame is the honest answer, the no-preview marker is not.
        allblack = os.path.join(tmp, "allblack.webm")
        check("built an all-black clip", make_clip(allblack, black=5, colour=0))
        forget(m, allblack)
        aimg = m.make_thumb(allblack)
        check("a clip that is blank all through still gets its (blank) frame",
              not aimg.isNull() and m._is_blank(aimg))

        # ---- 3. the shared freedesktop cache ---------------------------------
        cached = m.THUMB_ROOT / "large" / (m._thumb_hash(webm) + ".png")
        check("it is written into the shared thumbnail cache", cached.exists(), str(cached))
        t0 = time.time()
        img2 = m.make_thumb(webm)
        warm = time.time() - t0
        check("the second visit is a cache read, not another ffmpeg",
              not img2.isNull() and warm < cold / 4,
              "cold %.3fs, warm %.3fs" % (cold, warm))
        # a re-encode changes the mtime, so the cached entry must be rejected
        os.utime(webm, (time.time() + 5, time.time() + 5))
        check("a changed source invalidates the cached poster frame",
              m._valid_for(cached, os.stat(webm).st_mtime) is None)

        # ---- 4. mp4 too, and a container ffprobe reports no duration for -----
        mp4 = os.path.join(tmp, "clip.mp4")
        check("built a test .mp4", make_clip(mp4, codec="libx264"))
        forget(m, mp4)
        check("an mp4 gets a thumbnail", not m.make_thumb(mp4).isNull())

        # ---- 5. failures are marked, not retried for ever --------------------
        bogus = os.path.join(tmp, "notreally.mp4")
        open(bogus, "w").write("this is not a video")
        forget(m, bogus)
        check("a file that only looks like a video yields no thumbnail",
              m.make_thumb(bogus).isNull())
        check("...and leaves a fail marker so it is not re-attempted",
              m._fail_path(bogus).exists())

        # ---- 6. the oversized-source guard is for stills, not video ----------
        big_png = os.path.join(tmp, "big.png")
        write_png(big_png)
        forget(m, big_png)
        real_cap, m.THUMB_MAX_SRC = m.THUMB_MAX_SRC, 10   # 10 bytes: everything is "huge"
        try:
            check("an oversized STILL is skipped", m.make_thumb(big_png).isNull())
            forget(m, webm)
            check("an oversized VIDEO is thumbnailed anyway — its cost is one "
                  "keyframe, not the file", not m.make_thumb(webm).isNull())
        finally:
            m.THUMB_MAX_SRC = real_cap

        # ---- 7. the real Main.qml puts video in the preview grid -------------
        tiles = _grid_tiles(app, tmp)
        names = sorted(e["name"] for e in tiles["previews"])
        check("the preview grid takes video entries beside images",
              "clip.webm" in names and "clip.mp4" in names and "big.png" in names, names)
        # The play marker, read off the scene graph rather than a screenshot: a
        # video tile wears it and a still tile does not. `isVideo` alone would
        # not catch the chip failing to build.
        flags = {k: v for k, v in tiles.items() if k != "previews"}
        check("a video tile is flagged isVideo and a still one is not",
              tiles["video_isVideo"] is True and tiles["image_isVideo"] is False, flags)
        check("both kinds request a thumbnail", tiles["video_hasThumb"] is True
              and tiles["image_hasThumb"] is True, flags)
        check("the play chip is BUILT on the video tile only — a still must not "
              "pay for nine items it never shows",
              tiles["video_chip"] is True and tiles["image_chip"] is False, flags)
        check("the chip's marker is drawn from 7 rows, not a font glyph",
              tiles.get("chip_rows") == 7, tiles.get("chip_rows"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("all checks passed")
    return 0


def _viewer_video_exts():
    """viewer's VIDEO_EXTS read out of its source rather than imported: importing
    apps/viewer/main.py would run the whole app."""
    src = open(os.path.join(os.path.dirname(FILER), "viewer", "main.py")).read()
    start = src.index("VIDEO_EXTS = {")
    body = src[start + len("VIDEO_EXTS = "):]
    depth, end = 0, 0
    for i, ch in enumerate(body):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    return eval(body[:end])           # a set literal of string constants


def _grid_tiles(app, d):
    """Load the real Main.qml on `d` and report what the preview grid built: the
    `previews` model plus the state of one video tile and one still tile. Reuses
    dragsource-test's engine setup and its childItems()-aware tree walk (a view's
    delegates are only VISUAL children, so `children()` never reaches them)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dragsrc", os.path.join(FILER, "tools", "dragsource-test.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    engine, win, keep = mod.build(app, d)
    mod.spin(1200)
    pane = mod.find(win, "watchKey")
    out = {"previews": mod.unwrap(pane.property("previews")) or []}
    for want, tag in (("clip.webm", "video"), ("big.png", "image")):
        tile = next((o for o in mod.walk(pane)
                     if isinstance(mod.unwrap(_prop(o, "entry")), dict)
                     and mod.unwrap(_prop(o, "entry")).get("name") == want), None)
        out[tag + "_isVideo"] = tile and _prop(tile, "isVideo")
        out[tag + "_hasThumb"] = tile and _prop(tile, "hasThumb")
        loader = next((o for o in mod.walk(tile)
                       if _prop(o, "sourceComponent") is not None), None) if tile else None
        out[tag + "_loaderActive"] = loader and _prop(loader, "active")
        chip = next((o for o in mod.walk(tile) if _prop(o, "radius") == 2
                     and _prop(o, "width") == 15), None) if tile else None
        out[tag + "_chip"] = chip is not None
        if chip is not None and tag == "video":
            out["chip_rows"] = len([o for o in mod.walk(chip)
                                    if _prop(o, "height") == 1])
    return out


def _prop(o, name):
    try:
        return o.property(name)
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
