"""imgconv — filer's "copy under 4MB" for stills.

The picture side of what `videoconv.py` does for clips: right-click an image
that is too big for whatever you are about to paste it into, get a copy next to
it that fits, without being asked a single question about quality or format.
Same shape as its sibling — a copy beside the original, a desktop toast, and
`finished(outPath)` so the view lands the selection on the new file — and
deliberately much smaller, because a still needs no ffprobe, no encoder choice
and no progress stream.

**The search itself is `pylib/imgfit.py`** — quality first then resolution,
measured by encoding into a QBuffer, JPEG unless the alpha is really used. It
moved there on 2026-08-06 when painter needed the same budget for the collage
it hands to a drag; what stays here is the part that is filer's: naming the copy
beside the original, the toast, and the QObject the menu talks to. Everything
that file documents applies unchanged, including its process-wide lift of Qt's
256 MB decode ceiling — which is also what gives filer's thumbnailer preview
tiles for very large PNGs.

What it refuses, out loud, rather than doing badly: an animated source (one
frame of a GIF is not a copy of it), an image Qt cannot decode, and one that
will not fit even at the smallest scale and lowest quality.
"""
import os
import threading

from PySide6.QtCore import QObject, Signal, Slot

from notify import toast as _toast_send
from imgfit import (LIMIT, TARGET, best_under, encode, fit, read,
                    uses_alpha)

# Kept as names here because filer's own harness and AGENTS.md cite them; the
# values, and the reasoning for them, are imgfit's.
__all__ = ["LIMIT", "TARGET", "out_path_for", "shrink", "ImgConv"]


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


# The harness (and any caller that grew used to them) reaches these by their
# old names; the implementations are imgfit's, so there is exactly one of each.
_uses_alpha = uses_alpha
_encode = encode
_best_under = best_under


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

    img, why = read(src)
    if img is None:
        return {"ok": False, "reason": why}

    res = fit(img, budget)
    if not res["ok"]:
        return res
    dst = out_path_for(src, res["ext"])
    try:
        with open(dst, "wb") as f:
            f.write(res["bytes"])
    except OSError as e:
        return {"ok": False, "reason": str(e)}
    px = "%dx%d" % (res["width"], res["height"])
    summary = "%s -> %s, %s" % (_human(size), _human(len(res["bytes"])), px)
    if res["scale"] != 1.0:
        summary += " (was %dx%d)" % (img.width(), img.height())
    return {"ok": True, "path": dst, "bytes": len(res["bytes"]),
            "quality": res["quality"], "summary": summary}


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
