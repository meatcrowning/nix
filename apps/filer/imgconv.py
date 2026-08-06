"""imgconv — filer's "copy under 4MB" for stills.

The picture side of what `videoconv.py` does for clips: right-click an image
that is too big for whatever you are about to paste it into, get a copy next to
it that fits, without being asked a single question about quality or format.
Same shape as its sibling — a copy beside the original, a desktop toast, and
`finished(outPath)` so the view lands the selection on the new file — and
deliberately much smaller, because a still needs no ffprobe, no encoder choice
and no progress stream.

The search. There are two knobs, and they are not equal: **quality first, then
resolution.** Re-encoding a photo at a lower JPEG quality costs detail you have
to look for; throwing away pixels costs detail that is simply gone. So each
scale in `SCALES` is tried with a binary search over quality, and the next
(smaller) scale is only reached when even the floor quality at this one will not
fit. The first size that fits wins, so an image barely over the line comes back
full-resolution at high quality and only a genuinely huge one gets scaled.

Everything is measured by encoding into memory (`QBuffer`), never by writing
files and stat-ing them: the search does five to ten encodes and none of them
but the winner should ever touch the disk.

Format. JPEG, except when the source actually uses its alpha channel, where the
result is WebP — lossy WebP keeps transparency, and flattening onto an invented
background colour would be a silent, wrong answer. `hasAlphaChannel()` is not
enough to decide that: a PNG saved by almost anything carries an alpha channel
that is opaque everywhere, and answering "webp" for those would make the common
case a format nobody asked for. So the alpha is *sampled* (`_uses_alpha`).

What it refuses, out loud, rather than doing badly: an animated source (one
frame of a GIF is not a copy of it), an image Qt cannot decode, and one that
will not fit even at the smallest scale and lowest quality.
"""
import os
import threading

from PySide6.QtCore import QObject, QBuffer, QIODevice, Signal, Slot
from PySide6.QtGui import QImage, QImageReader, QImageWriter
from PySide6.QtCore import Qt

from notify import toast as _toast_send

# "4MB" as every upload form means it: 4 million bytes is under both readings
# of the number (4e6 and 4*1024^2), so a file that passes here passes there.
# Same reasoning as videoconv.LIMIT, and the same 7% head-room, since the
# search measures the real encoded bytes and can stop as soon as it is under.
LIMIT = 4_000_000
TARGET = int(LIMIT * 0.93)

# Resolution rungs, as a fraction of the source's longest side. Only reached
# when quality alone cannot pay for the budget at the rung above.
SCALES = (1.0, 0.85, 0.7, 0.6, 0.5, 0.4, 0.32, 0.25, 0.18, 0.12)

# Quality window for the binary search. The floor is where JPEG starts to look
# obviously chewed; below it, dropping resolution is the better trade — which
# is exactly what the next scale does.
Q_MIN, Q_MAX = 40, 92

# A source this big is not a photograph that lost its way, it is a scan or a
# render, and decoding it uncompressed would cost more RAM than book has.
MAX_SRC_PIXELS = 120_000_000

# Qt refuses to decode any image whose uncompressed form exceeds 256 MB, and
# reports it as the thoroughly misleading "Unable to read image data" — so the
# images most worth shrinking are the ones that silently could not be. Measured
# on top: a 9000x8113 PNG (73 MP, 292 MB as ARGB32) failed outright and decoded
# fine with the limit raised. `MAX_SRC_PIXELS` above is the real guard, so the
# limit is set to what that allows and no more.
#
# This is a PROCESS-WIDE static, not a per-reader setting, so it also lifts the
# same ceiling off filer's thumbnailer (main.py) — which is a fix, not a side
# effect: those same PNGs had no preview tile for exactly this reason.
QImageReader.setAllocationLimit(MAX_SRC_PIXELS * 4 // (1024 * 1024) + 1)


def out_path_for(src, ext):
    """`photo.png` -> `photo-4mb.jpg`, next to the source, never clobbering an
    existing file (`-4mb-2.jpg`, …). Mirrors videoconv.out_path_for."""
    stem = os.path.splitext(str(src))[0]
    cand = "%s-4mb.%s" % (stem, ext)
    n = 2
    while os.path.lexists(cand):
        cand = "%s-4mb-%d.%s" % (stem, n, ext)
        n += 1
    return cand


def _human(b):
    b = float(b)
    for u in ("B", "K", "M", "G"):
        if b < 1024 or u == "G":
            return "%dB" % b if u == "B" else "%.1f%s" % (b, u)
        b /= 1024


def _uses_alpha(img):
    """Whether the image is actually transparent anywhere, not merely carrying
    an alpha channel. Sampled on a 64x64 reduction — enough to catch a logo's
    cut-out corner, cheap enough to run on a 100-megapixel source, and the same
    trick `videoconv._is_blank` uses to avoid touching every pixel."""
    if not img.hasAlphaChannel():
        return False
    small = img.scaled(64, 64, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    small = small.convertToFormat(QImage.Format_ARGB32)
    for y in range(small.height()):
        for x in range(small.width()):
            if small.pixelColor(x, y).alpha() < 255:
                return True
    return False


def _encode(img, fmt, quality):
    """`img` as `fmt` at `quality`, in memory. Returns the bytes, or None if the
    writer refused (an unsupported format on this machine's Qt build)."""
    # QBuffer() with no argument, using its OWN internal byte array. Handing it
    # `QByteArray()` instead makes the buffer borrow a Python-owned temporary
    # that is collected while the JPEG writer is still filling it — measured, a
    # hard SEGV inside QBuffer::writeData on the first encode.
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    w = QImageWriter(buf, fmt.encode())
    w.setQuality(quality)
    if not w.write(img):
        return None
    return bytes(buf.data())


def _best_under(img, fmt, budget):
    """The largest quality whose encoding of `img` fits `budget`, as (quality,
    bytes) — or None if even Q_MIN is too big. Binary search: ~5 encodes."""
    lo, hi, best = Q_MIN, Q_MAX, None
    floor = _encode(img, fmt, Q_MIN)
    if floor is None or len(floor) > budget:
        return None
    best = (Q_MIN, floor)
    while lo <= hi:
        mid = (lo + hi) // 2
        blob = _encode(img, fmt, mid)
        if blob is not None and len(blob) <= budget:
            best = (mid, blob)
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def shrink(src, budget=TARGET):
    """Do the whole job, synchronously. Returns a dict:

        {"ok": True,  "path": <written file>, "bytes": n, "summary": str}
        {"ok": False, "reason": str}

    Pure apart from the one file it writes at the end, so a harness can run it
    on a temp directory with no Qt event loop and no filer around it."""
    src = str(src)
    try:
        size = os.path.getsize(src)
    except OSError as e:
        return {"ok": False, "reason": str(e)}
    if size <= LIMIT:
        return {"ok": False, "reason": "already under 4MB"}

    reader = QImageReader(src)
    reader.setAutoTransform(True)      # honour the EXIF rotation, once, here
    if not reader.canRead():
        return {"ok": False, "reason": "not an image this machine can read"}
    if reader.imageCount() > 1:
        return {"ok": False, "reason": "that is an animation, not a still"}
    dims = reader.size()
    if dims.isValid() and dims.width() * dims.height() > MAX_SRC_PIXELS:
        return {"ok": False, "reason": "image is too large to decode (%d MP)"
                % (dims.width() * dims.height() // 1_000_000)}
    img = reader.read()
    if img.isNull():
        return {"ok": False, "reason": reader.errorString() or "could not decode it"}

    fmt = "webp" if _uses_alpha(img) else "jpeg"
    if fmt.encode() not in [bytes(b) for b in QImageWriter.supportedImageFormats()]:
        fmt = "jpeg"                   # no webp in this Qt build; alpha is lost
    ext = "webp" if fmt == "webp" else "jpg"

    long_side = max(img.width(), img.height())
    for scale in SCALES:
        cand = img if scale == 1.0 else img.scaled(
            max(1, int(round(img.width() * scale))),
            max(1, int(round(img.height() * scale))),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        hit = _best_under(cand, fmt, budget)
        if hit is None:
            continue
        quality, blob = hit
        dst = out_path_for(src, ext)
        try:
            with open(dst, "wb") as f:
                f.write(blob)
        except OSError as e:
            return {"ok": False, "reason": str(e)}
        px = "%dx%d" % (cand.width(), cand.height())
        summary = "%s -> %s, %s" % (_human(size), _human(len(blob)), px)
        if scale != 1.0:
            summary += " (was %dx%d)" % (img.width(), img.height())
        return {"ok": True, "path": dst, "bytes": len(blob), "quality": quality,
                "summary": summary}
    return {"ok": False,
            "reason": "cannot get it under 4MB (tried down to %d%% of %dpx)"
                      % (SCALES[-1] * 100, long_side)}


class ImgConv(QObject):
    """The `ImgConv` context property. One slot the menu calls, one signal the
    window listens to. The work runs on a thread — a big JPEG search is a
    second or two of CPU and the window must stay live — and the only thing
    that crosses back is a Qt signal, which Qt queues onto the GUI thread."""

    finished = Signal(str)     # the written path; "" on failure

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = set()
        self._lock = threading.Lock()

    @Slot(str, result=bool)
    def isBusy(self, path):
        with self._lock:
            return str(path) in self._busy

    @Slot(str)
    def start(self, path):
        """Begin (or refuse) a shrink. Safe straight from the menu: it re-checks
        everything itself, so nothing depends on what the menu believed."""
        src = str(path)
        with self._lock:
            if src in self._busy:
                return
            self._busy.add(src)
        threading.Thread(target=self._run, args=(src,), daemon=True).start()

    def _run(self, src):
        name = os.path.basename(src)
        nid = _toast_send("copying " + name, "under 4MB", persist=True)
        try:
            res = shrink(src)
        except Exception as e:                       # noqa: BLE001 — a decode
            res = {"ok": False, "reason": str(e)}    # blowing up must still toast
        finally:
            with self._lock:
                self._busy.discard(src)
        if res.get("ok"):
            _toast_send("copied " + os.path.basename(res["path"]),
                        res["summary"], replace_id=nid)
            self.finished.emit(res["path"])
        else:
            _toast_send("can't copy " + name + " under 4MB",
                        res.get("reason", "?"), urgency="critical", replace_id=nid)
            self.finished.emit("")
