"""imgfit — get an image under a byte budget, at the best quality that fits.

THE one image-budget search for these apps. It was filer's, inside
`filer/imgconv.py` ("copy under 4MB"), until painter needed the same thing for
the collage it hands to a drag — so the SEARCH lives here and the callers keep
only what is theirs: filer writes a file beside the original and toasts,
painter writes one into its cache and puts it on a drag.

The search. There are two knobs and they are not equal: **quality first, then
resolution.** Re-encoding at a lower JPEG quality costs detail you have to look
for; throwing away pixels costs detail that is simply gone. So each scale in
`SCALES` gets a binary search over quality, and the next (smaller) scale is
reached only when even `Q_MIN` will not fit at this one. An image barely over
the line therefore comes back FULL RESOLUTION, and only a genuinely huge one is
scaled.

Everything is measured by encoding into memory (`QBuffer`), never by writing
files and stat-ing them: a search is five to ten encodes and none but the
winner should ever touch a disk.

Format. JPEG, except where the source actually uses its alpha channel, which
becomes lossy WebP — flattening transparency onto an invented background is a
silent wrong answer. `hasAlphaChannel()` is not enough to decide it: a PNG from
almost any tool carries an alpha channel that is opaque everywhere, so the
alpha is SAMPLED (`uses_alpha`).
"""
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QImageReader, QImageWriter

# "4MB" as every upload form means it: 4 million bytes is under both readings
# of the number (4e6 and 4*1024^2), so a file that passes here passes there.
# The 7% head-room costs nothing — the search measures real encoded bytes and
# stops as soon as it is under.
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
# fine with the limit raised. `MAX_SRC_PIXELS` is the real guard, so the limit
# is set to what that allows and no more.
#
# This is a PROCESS-WIDE static, not a per-reader setting, so importing this
# module also lifts the ceiling off the importer's own thumbnailing — which is a
# fix, not a side effect: in filer those same PNGs had no preview tile for
# exactly this reason.
QImageReader.setAllocationLimit(MAX_SRC_PIXELS * 4 // (1024 * 1024) + 1)


def uses_alpha(img):
    """Whether the image is actually transparent anywhere, not merely carrying
    an alpha channel. Sampled on a 64x64 reduction — enough to catch a logo's
    cut-out corner, cheap enough to run on a 100-megapixel source."""
    if not img.hasAlphaChannel():
        return False
    small = img.scaled(64, 64, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    small = small.convertToFormat(QImage.Format_ARGB32)
    for y in range(small.height()):
        for x in range(small.width()):
            if small.pixelColor(x, y).alpha() < 255:
                return True
    return False


def encode(img, fmt, quality):
    """`img` as `fmt` at `quality`, in memory. Returns the bytes, or None if the
    writer refused (a format this machine's Qt build has no plugin for)."""
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


def best_under(img, fmt, budget):
    """The highest quality whose encoding of `img` fits `budget`, as (quality,
    bytes) — or None if even Q_MIN is too big. Binary search: ~5 encodes."""
    lo, hi = Q_MIN, Q_MAX
    floor = encode(img, fmt, Q_MIN)
    if floor is None or len(floor) > budget:
        return None
    best = (Q_MIN, floor)
    while lo <= hi:
        mid = (lo + hi) // 2
        blob = encode(img, fmt, mid)
        if blob is not None and len(blob) <= budget:
            best = (mid, blob)
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def format_for(img):
    """(format, extension) for an image: jpeg unless its alpha is really used,
    and jpeg anyway on a Qt build with no webp writer."""
    fmt = "webp" if uses_alpha(img) else "jpeg"
    if fmt.encode() not in [bytes(b) for b in QImageWriter.supportedImageFormats()]:
        fmt = "jpeg"                   # no webp here; alpha is lost
    return fmt, ("webp" if fmt == "webp" else "jpg")


def fit(img, budget=TARGET, fmt=None, ext=None):
    """The whole search, on an image already in memory. Returns

        {"ok": True,  "bytes": b"...", "format": "jpeg", "ext": "jpg",
         "quality": 88, "width": w, "height": h, "scale": 1.0}
        {"ok": False, "reason": str}

    and writes nothing — the caller decides where the bytes go."""
    if img is None or img.isNull():
        return {"ok": False, "reason": "nothing to encode"}
    if fmt is None:
        fmt, ext = format_for(img)
    ext = ext or ("webp" if fmt == "webp" else "jpg")
    for scale in SCALES:
        cand = img if scale == 1.0 else img.scaled(
            max(1, int(round(img.width() * scale))),
            max(1, int(round(img.height() * scale))),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        hit = best_under(cand, fmt, budget)
        if hit is None:
            continue
        quality, blob = hit
        return {"ok": True, "bytes": blob, "format": fmt, "ext": ext,
                "quality": quality, "width": cand.width(), "height": cand.height(),
                "scale": scale}
    return {"ok": False,
            "reason": "cannot get it under %d bytes (tried down to %d%% of %dpx)"
                      % (budget, SCALES[-1] * 100, max(img.width(), img.height()))}


def read(path):
    """Decode a file the way both callers want it: EXIF rotation applied, an
    animation refused, an absurd source refused. Returns (QImage, reason)."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)      # honour the EXIF rotation, once, here
    if not reader.canRead():
        return None, "not an image this machine can read"
    if reader.imageCount() > 1:
        return None, "that is an animation, not a still"
    dims = reader.size()
    if dims.isValid() and dims.width() * dims.height() > MAX_SRC_PIXELS:
        return None, ("image is too large to decode (%d MP)"
                      % (dims.width() * dims.height() // 1_000_000))
    img = reader.read()
    if img.isNull():
        return None, (reader.errorString() or "could not decode it")
    return img, ""
