"""collage.py — several outputs as ONE picture, for a drag.

Dragging a multi-selection out of the gallery does not hand over five files: it
hands over one image with all five in it, at the best quality that fits a 4MB
budget ([his] *"when i click and drag them, what gets put down where the cursor
lies is a collage of them in the highest quality under 4mb"*). Five separate
files land five different ways depending on what catches them; one picture
lands the same way everywhere, and 4MB is what every upload form and chat box
takes.

The budget search is `pylib/imgfit.py` — the same one filer's "copy under 4MB"
uses, quality before resolution — so this file is only the arrangement:

- **A grid whose cell has the SHAPE of what is in it.** The cell aspect is the
  mean of the sources', clamped, rather than a square: a set of 2:3 portraits
  laid into squares is a collage that is mostly background.
- **Each image is fitted, never cropped.** A crop decides for him which part of
  his own output matters.
- **Row-major in the order given**, which is the gallery's own (newest first),
  so the picture reads the way the grid he selected in does.

Nothing here writes a file: `render()` returns a QImage and `encode()` the
bytes. The caller (painter's `Painter._build_collage`) decides where they go,
which is what lets the whole thing run on a worker thread with no Qt event loop.
"""
import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

import imgfit

# The gap between cells, and the ground they sit on. Black rather than the
# theme's `bg`: a collage is dropped into somebody else's window, where this
# desktop's palette means nothing.
GAP = 8
BG = QColor("#000000")

# The cell's long side before the budget search gets to it. Big enough that a
# 3x3 collage starts at ~3000px and the search decides the real size from the
# bytes rather than from a number picked here.
CELL = 1024

# How far the cell may follow its content's shape. Beyond this the odd one out
# in a mixed selection costs everything else too much room.
MIN_ASPECT, MAX_ASPECT = 0.5, 2.0


def grid_for(n):
    """(cols, rows) for n tiles — as square an arrangement as n allows."""
    if n <= 0:
        return (0, 0)
    cols = int(math.ceil(math.sqrt(n)))
    rows = int(math.ceil(n / float(cols)))
    return (cols, rows)


def render(images, cell=None):
    """Lay `images` (QImages, in order) out as one QImage. None on an empty
    list; a single image is returned as itself, since a collage of one is it."""
    images = [im for im in images if im is not None and not im.isNull()]
    if not images:
        return None
    if len(images) == 1:
        return images[0]

    # NEVER UPSCALE INTO THE CELL. The budget is spent on real pixels or on
    # interpolated ones, and interpolated ones cost the same and carry nothing:
    # a set of 512px outputs laid into 1024px cells encodes to a bigger file
    # that shows less, so the search then scales the whole canvas back down.
    # The cap is what stops a 4K source making a 12K canvas.
    if cell is None:
        cell = min(CELL, max(im.height() for im in images))

    aspects = [im.width() / float(im.height()) for im in images if im.height()]
    mean = sum(aspects) / len(aspects) if aspects else 1.0
    mean = max(MIN_ASPECT, min(MAX_ASPECT, mean))
    cell_h = cell
    cell_w = max(1, int(round(cell * mean)))

    cols, rows = grid_for(len(images))
    width = cols * cell_w + (cols + 1) * GAP
    height = rows * cell_h + (rows + 1) * GAP

    canvas = QImage(width, height, QImage.Format_RGB32)
    canvas.fill(BG)
    p = QPainter(canvas)
    try:
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for i, im in enumerate(images):
            r, c = divmod(i, cols)
            box = QRectF(GAP + c * (cell_w + GAP), GAP + r * (cell_h + GAP),
                         cell_w, cell_h)
            scaled = im.scaled(int(box.width()), int(box.height()),
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
            # Centred in its cell: fitted, never cropped.
            p.drawImage(QRectF(box.x() + (box.width() - scaled.width()) / 2.0,
                               box.y() + (box.height() - scaled.height()) / 2.0,
                               scaled.width(), scaled.height()),
                        scaled)
    finally:
        p.end()
    return canvas


def encode(images, budget=imgfit.TARGET):
    """render() + the budget search. Returns imgfit.fit()'s dict, with the
    canvas size added, or {"ok": False, "reason": ...}."""
    canvas = render(images)
    if canvas is None:
        return {"ok": False, "reason": "nothing to lay out"}
    # A collage is opaque by construction (it is drawn onto BG), so the format
    # question imgfit asks of a lone image has one answer here — and asking it
    # anyway would sample the alpha of a canvas that has none.
    res = imgfit.fit(canvas, budget, fmt="jpeg", ext="jpg")
    if res.get("ok"):
        res["canvas"] = (canvas.width(), canvas.height())
    return res


def read_all(paths):
    """Decode a list of paths in order. Returns (images, problems); a file that
    will not decode is SKIPPED with its reason rather than failing the lot —
    one unreadable output must not cost him the other four."""
    images, problems = [], []
    for path in paths:
        img, why = imgfit.read(path)
        if img is None:
            problems.append("%s: %s" % (path, why))
            continue
        images.append(img)
    return images, problems
