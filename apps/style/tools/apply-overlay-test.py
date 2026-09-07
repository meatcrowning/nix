#!/usr/bin/env python3
"""Offscreen-free regression tests for apply-overlay's controller-state rules."""

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from overlay_state import progress, should_show, status_for_generation  # noqa: E402


def check(label, got, want):
    if got != want:
        raise SystemExit(f"FAIL {label}: got {got!r}, want {want!r}")
    print(f"ok {label}")


live = {"generation": 4, "state": "applying", "fraction": 0.25,
        "detail": "Applying prepared wallpaper and colors"}
check("same generation stays live", status_for_generation(live, 4), "applying")
check("fast applies never map an overlay", should_show(119, live, 4), False)
check("slow applies map an overlay", should_show(120, live, 4), True)
check("an older status cannot map a new overlay", should_show(900, {"generation": 3, "state": "complete"}, 4), False)
check("controller fraction/detail are used", progress(live, 4),
      (0.25, "Applying prepared wallpaper and colors"))
check("completion closes instead of presenting", should_show(900, {"generation": 4, "state": "complete"}, 4), False)
check("newer generation supersedes old overlay", status_for_generation({"generation": 5, "state": "applying"}, 4), "superseded")
check("bad fractions are bounded", progress({"generation": 4, "state": "applying", "fraction": 7}, 4), (1.0, ""))
print("apply-overlay-test: all checks passed")
