#!/usr/bin/env python3
"""Build a borderless PNG collage from image paths supplied by Dolphin."""

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile


TARGET_ASPECT = 16 / 10
MAX_CELL_HEIGHT = 1600


def dimensions(path):
    """Return an image's first video-stream dimensions, or None."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "json", os.fspath(path)],
        capture_output=True, text=True, check=False,
    )
    try:
        stream = json.loads(probe.stdout)["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        return (width, height) if width > 0 and height > 0 else None
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def layout(sizes):
    """Choose the compact near-landscape grid that wastes the least space."""
    count = len(sizes)
    aspect = statistics.median(width / height for width, height in sizes)
    aspect = max(0.5, min(2.0, aspect))
    choices = []
    for cols in range(1, count + 1):
        rows = math.ceil(count / cols)
        canvas_aspect = cols * aspect / rows
        empty = cols * rows - count
        # The first term keeps the finished image naturally viewable. The small
        # penalties make an exact grid win over a near tie and avoid portrait
        # canvases unless the selected images themselves call for one.
        score = abs(math.log(canvas_aspect / TARGET_ASPECT)) + 0.16 * empty / count
        if canvas_aspect < 1:
            score += 0.06
        choices.append((score, cols, rows, aspect))
    _, cols, rows, aspect = min(choices)
    cell_h = min(MAX_CELL_HEIGHT, int(statistics.median(height for _, height in sizes)))
    cell_h = max(1, cell_h)
    return cols, rows, max(1, round(cell_h * aspect)), cell_h


def output_path(cwd):
    """Never overwrite a previous collage; pick collage-2.png, then -3, …"""
    candidate = cwd / "collage.png"
    number = 2
    while candidate.exists():
        candidate = cwd / ("collage-%d.png" % number)
        number += 1
    return candidate


def command(paths, sizes, output):
    cols, rows, cell_w, cell_h = layout(sizes)
    filters = []
    labels = []
    for index in range(len(paths)):
        label = "v%d" % index
        # Fill each cell, then crop: the grid has neither gutters nor letterbox
        # bars. `setsar` avoids a non-square-pixel input changing the geometry.
        filters.append(
            "[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,"
            "crop=%d:%d,setsar=1,format=rgba[%s]" %
            (index, cell_w, cell_h, cell_w, cell_h, label)
        )
        labels.append("[%s]" % label)
    missing = cols * rows - len(paths)
    for index in range(missing):
        label = "blank%d" % index
        filters.append("color=c=black@0:s=%dx%d:d=1,format=rgba[%s]" %
                       (cell_w, cell_h, label))
        labels.append("[%s]" % label)
    layout_text = "|".join("%d_%d" % ((index % cols) * cell_w, (index // cols) * cell_h)
                           for index in range(cols * rows))
    filters.append("%sxstack=inputs=%d:layout=%s:fill=black@0,format=rgba[out]" %
                   ("".join(labels), cols * rows, layout_text))
    return (["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error"] +
            sum((["-i", os.fspath(path)] for path in paths), []) +
            ["-filter_complex", ";".join(filters), "-map", "[out]", "-frames:v", "1",
             "-pix_fmt", "rgba", os.fspath(output)])


def make_collage(paths, cwd):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg is not available")
    sizes, images = [], []
    for path in paths:
        size = dimensions(path)
        if size is not None:
            images.append(path)
            sizes.append(size)
    if len(images) < 2:
        raise RuntimeError("select at least two readable images")
    output = output_path(cwd)
    with tempfile.NamedTemporaryFile(prefix=".%s." % output.stem, suffix=".png",
                                     dir=cwd, delete=False) as temp:
        temp_path = Path(temp.name)
    try:
        result = subprocess.run(command(images, sizes, temp_path), capture_output=True,
                                text=True, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "ffmpeg could not make the collage")
        os.replace(temp_path, output)
    finally:
        temp_path.unlink(missing_ok=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    try:
        paths = [Path(path).expanduser().resolve() for path in args.paths]
        output = make_collage(paths, paths[0].parent)
    except (OSError, RuntimeError, ValueError) as exc:
        print("konsole-collage: %s" % exc, file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
