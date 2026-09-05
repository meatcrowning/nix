#!/usr/bin/env python3
"""Build a borderless JPEG collage from paths selected in Konsole.

Konsole passes the selected terminal text and the session's working directory.
The text may be one path per line or shell-quoted paths; all resolution stays
inside that directory unless a selected path is absolute.
"""

import argparse
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile


TARGET_ASPECT = 16 / 10
MAX_CELL_HEIGHT = 1600


def selected_paths(text, cwd):
    """Resolve selection text into distinct regular files, preserving order."""
    lines = [line.strip() for line in text.replace("\r", "").splitlines() if line.strip()]
    # `ls -1` makes the common path unambiguous, including filenames with spaces.
    raw = lines if lines and all((Path(line) if Path(line).is_absolute() else cwd / line).is_file()
                                 for line in lines) else shlex.split(text)
    paths, seen = [], set()
    for item in raw:
        path = Path(item).expanduser()
        if not path.is_absolute():
            path = cwd / path
        path = path.resolve()
        if path.is_file() and path not in seen:
            paths.append(path)
            seen.add(path)
    return paths


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
    """Never overwrite a previous collage; pick collage-2.jpg, then -3, …"""
    candidate = cwd / "collage.jpg"
    number = 2
    while candidate.exists():
        candidate = cwd / ("collage-%d.jpg" % number)
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
            "crop=%d:%d,setsar=1[%s]" % (index, cell_w, cell_h, cell_w, cell_h, label)
        )
        labels.append("[%s]" % label)
    missing = cols * rows - len(paths)
    for index in range(missing):
        label = "blank%d" % index
        filters.append("color=c=black:s=%dx%d:d=1[%s]" % (cell_w, cell_h, label))
        labels.append("[%s]" % label)
    layout_text = "|".join("%d_%d" % ((index % cols) * cell_w, (index // cols) * cell_h)
                           for index in range(cols * rows))
    filters.append("%sxstack=inputs=%d:layout=%s:fill=black[out]" %
                   ("".join(labels), cols * rows, layout_text))
    return (["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error"] +
            sum((["-i", os.fspath(path)] for path in paths), []) +
            ["-filter_complex", ";".join(filters), "-map", "[out]", "-frames:v", "1",
             "-q:v", "2", os.fspath(output)])


def make_collage(text, cwd):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg is not available")
    paths = selected_paths(text, cwd)
    sizes, images = [], []
    for path in paths:
        size = dimensions(path)
        if size is not None:
            images.append(path)
            sizes.append(size)
    if len(images) < 2:
        raise RuntimeError("select at least two readable images")
    output = output_path(cwd)
    with tempfile.NamedTemporaryFile(prefix=".%s." % output.stem, suffix=".jpg",
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
    parser.add_argument("--cwd", required=True, type=Path)
    parser.add_argument("selection")
    args = parser.parse_args()
    try:
        output = make_collage(args.selection, args.cwd.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        print("konsole-collage: %s" % exc, file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
