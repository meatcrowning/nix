#!/usr/bin/env python3
"""Hermetic timing probe for Painter's cold gallery scan.

Runs against synthetic local and peer output trees under a temporary directory.
No window, backend, real output directory, cache, or user state is touched.

    painter-qtenv python3 apps/painter/tools/gallery-bench.py
"""

from __future__ import annotations

import argparse
import cProfile
import io
import os
import pstats
import statistics
import sys
import tempfile
import time
from pathlib import Path


def populate(root: Path, count: int, offset: int = 0) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        path = root / f"painter_{i + offset:06d}_.png"
        path.touch()
        stamp = 1_700_000_000 + i
        os.utime(path, (stamp, stamp))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="100,1000,5000")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    sizes = [int(value) for value in args.sizes.split(",") if value]

    with tempfile.TemporaryDirectory(prefix="painter-gallery-bench-") as tmp:
        base = Path(tmp)
        local = base / "out"
        peer = base / "peer"
        os.environ.update({
            "PAINTER_OUT": str(local),
            "PAINTER_PEER_OUT": str(peer),
            "XDG_CACHE_HOME": str(base / "cache"),
            "XDG_STATE_HOME": str(base / "state"),
            "QT_QPA_PLATFORM": "offscreen",
        })

        painter = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(painter.parent / "pylib"))
        sys.path.insert(0, str(painter))
        from PySide6.QtCore import QCoreApplication  # noqa: PLC0415
        import gallery as app  # noqa: PLC0415

        qt = QCoreApplication.instance() or QCoreApplication([sys.argv[0]])

        class ScanGallery(app.Gallery):
            # Preview production is deliberately outside this benchmark. It is
            # already asynchronous; this measures the synchronous cold path.
            def _want_thumb(self, row):
                pass

            def _want_poster(self, path):
                pass

        previous = 0
        for size in sizes:
            populate(local, size - previous, previous)
            # Half as many peer-only rows plus duplicates of the oldest quarter.
            populate(peer, (size - previous) // 2, size + previous // 2)
            previous = size
            samples = []
            gallery = None
            for _ in range(max(1, args.rounds)):
                gallery = ScanGallery()
                started = time.perf_counter()
                gallery.load_existing()
                samples.append((time.perf_counter() - started) * 1000)
            print(f"{size:6d} local  {gallery.rowCount():6d} rows  "
                  f"median {statistics.median(samples):8.2f} ms  "
                  f"min {min(samples):8.2f} ms")

        if args.profile:
            gallery = ScanGallery()
            profiler = cProfile.Profile()
            profiler.enable()
            gallery.load_existing()
            profiler.disable()
            report = io.StringIO()
            pstats.Stats(profiler, stream=report).strip_dirs().sort_stats(
                "cumulative").print_stats(15)
            print(report.getvalue())
        del qt
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
