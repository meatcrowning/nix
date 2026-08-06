#!/usr/bin/env python3
"""imgconv-test — "copy under 4MB", offscreen and on generated images.

Builds its own sources in a temp directory (noise, so they do not compress
away; a flat gradient would fit under the budget at any quality and prove
nothing), runs the real `imgconv.shrink()` on them and asserts the properties
that matter:

  * the result is genuinely under the limit, and is a real decodable image;
  * quality is spent before resolution — an image only just over the line comes
    back at FULL resolution, and only one that cannot fit at any quality gets
    scaled;
  * transparency survives (a source that actually uses its alpha channel comes
    back as WebP with the alpha intact, not flattened onto an invented colour);
  * an opaque PNG does NOT become WebP just for carrying an alpha channel;
  * the refusals are refusals, with a reason: already small enough, an
    animation, something Qt cannot decode;
  * the output never clobbers a file that is already there.

Offscreen, self-contained, and it touches nothing outside its temp directory.

    ./tools/imgconv-test.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

FILER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FILER)
sys.path.insert(0, os.path.join(os.path.dirname(FILER), "pylib"))

from PySide6.QtGui import QGuiApplication, QImage, QImageReader  # noqa: E402

import imgconv  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def noisy(w, h, alpha=False):
    """An image that will not compress away: per-pixel pseudo-random colour, so
    the encoder has to actually spend bytes on it. Deterministic (no RNG — the
    repo's harnesses have to give the same answer twice)."""
    img = QImage(w, h, QImage.Format_ARGB32)
    s = 0x2545F491
    for y in range(h):
        row = []
        for x in range(w):
            s = (s * 1103515245 + 12345) & 0xFFFFFFFF
            r, g, b = (s >> 16) & 255, (s >> 8) & 255, s & 255
            a = 255
            if alpha and x < w // 4:
                a = 0                    # a transparent stripe down the left
            row.append((a << 24) | (r << 16) | (g << 8) | b)
        for x, v in enumerate(row):
            img.setPixel(x, y, v)
    return img


def animated_gif(path):
    """A genuinely animated GIF, over the 4MB limit — 60 frames of noise, which
    is both unmistakably multi-frame and too incompressible to slip under the
    line. Hand-assembling one was tried and is not worth it: Qt's gif reader
    reported imageCount()==1 for the two-frame file, so the harness silently
    skipped the very refusal it exists to check. Needs ffmpeg; returns False
    without it and the caller skips out loud."""
    if not shutil.which("ffmpeg"):
        return False
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "nullsrc=s=360x360:r=10:d=6,geq=random(1)*255:128:128",
                    "-pix_fmt", "rgb24", path], check=False)
    return os.path.exists(path) and os.path.getsize(path) > imgconv.LIMIT


def main():
    app = QGuiApplication(sys.argv)          # noqa: F841  (image plugins need it)
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    tmp = tempfile.mkdtemp(prefix="t_imgconv-")
    try:
        run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("all imgconv checks passed")
    return 0


def run(tmp):
    # ---- a source a little over the line: quality alone must pay for it ----
    big = os.path.join(tmp, "photo.png")
    src = noisy(1400, 1400)
    src.save(big, "png")
    size = os.path.getsize(big)
    check("the test source is over the limit", size > imgconv.LIMIT,
          "%.1f MB" % (size / 1e6))

    res = imgconv.shrink(big)
    check("it produced a copy", res.get("ok"), res.get("reason"))
    if res.get("ok"):
        out = res["path"]
        check("named beside the source", out == os.path.join(tmp, "photo-4mb.jpg"), out)
        check("the copy is under 4MB", os.path.getsize(out) <= imgconv.LIMIT,
              "%.2f MB" % (os.path.getsize(out) / 1e6))
        got = QImage(out)
        check("...and is a decodable image", not got.isNull())
        check("...at FULL resolution — quality is spent before pixels",
              (got.width(), got.height()) == (1400, 1400),
              "%dx%d" % (got.width(), got.height()))
        check("...and the source is untouched", os.path.getsize(big) == size)

    # ---- a second run must not clobber the first ----
    res2 = imgconv.shrink(big)
    check("a second copy gets its own name",
          res2.get("ok") and res2["path"].endswith("photo-4mb-2.jpg"), res2.get("path"))

    # ---- transparency survives, as WebP ----
    tp = os.path.join(tmp, "cutout.png")
    noisy(1400, 1400, alpha=True).save(tp, "png")
    if os.path.getsize(tp) > imgconv.LIMIT:
        r = imgconv.shrink(tp)
        check("a transparent source is copied", r.get("ok"), r.get("reason"))
        if r.get("ok"):
            check("...as webp, not jpeg", r["path"].endswith(".webp"), r["path"])
            got = QImage(r["path"])
            check("...with the transparency intact",
                  not got.isNull() and got.pixelColor(2, 2).alpha() == 0,
                  got.isNull() or got.pixelColor(2, 2).alpha())
    else:
        check("(transparent source was already small — skipped)", True)

    # ---- an OPAQUE png keeps jpeg, despite having an alpha channel ----
    src.convertToFormat(QImage.Format_ARGB32).save(os.path.join(tmp, "op.png"), "png")
    check("an opaque ARGB image is not treated as transparent",
          not imgconv._uses_alpha(QImage(os.path.join(tmp, "op.png"))))
    check("...and one with a hole is", imgconv._uses_alpha(noisy(64, 64, alpha=True)))

    # ---- the refusals ----
    small = os.path.join(tmp, "small.png")
    noisy(40, 40).save(small, "png")
    r = imgconv.shrink(small)
    check("an already-small file is refused, with the reason",
          not r["ok"] and "already under" in r["reason"], r.get("reason"))

    gif = os.path.join(tmp, "anim.gif")
    if animated_gif(gif):
        check("the animated source really is multi-frame and over the limit",
              QImageReader(gif).imageCount() > 1, QImageReader(gif).imageCount())
        r = imgconv.shrink(gif)
        check("an animation is refused, not silently flattened to one frame",
              not r["ok"] and "animation" in r["reason"], r.get("reason"))
        check("...and left no output behind",
              not os.path.exists(os.path.join(tmp, "anim-4mb.jpg")))
    else:
        check("(no ffmpeg here to build an animated gif — skipped)", True)

    junk = os.path.join(tmp, "notanimage.png")
    with open(junk, "wb") as f:
        f.write(os.urandom(5_000_000))
    r = imgconv.shrink(junk)
    check("an undecodable file is refused, not written", not r["ok"], r.get("reason"))
    check("...and left no output behind",
          not os.path.exists(os.path.join(tmp, "notanimage-4mb.jpg")))

    # ---- a budget nothing can meet ----
    r = imgconv.shrink(big, budget=200)
    check("an impossible budget is refused rather than approximated",
          not r["ok"] and "cannot get it under" in r["reason"], r.get("reason"))

    # ---- and the case that must SCALE: a real photo-sized source, tiny budget
    r = imgconv.shrink(big, budget=60_000)
    check("a budget quality cannot reach falls back to scaling", r.get("ok"), r.get("reason"))
    if r.get("ok"):
        got = QImage(r["path"])
        check("...so the copy is smaller than the source in pixels too",
              got.width() < 1400, "%dx%d" % (got.width(), got.height()))
        check("...and inside the budget", os.path.getsize(r["path"]) <= 60_000,
              os.path.getsize(r["path"]))


if __name__ == "__main__":
    sys.exit(main())
