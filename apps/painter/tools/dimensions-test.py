#!/usr/bin/env python3
"""Resolution round trips without preferences, desktop or backend access."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dimensions import calc_dims, controls_for_size

assert calc_dims('1:1', .082944, 64) == (256, 256)
assert controls_for_size(1408, 2128, 16) == dict(aspectW=2, aspectH=3, megapixels=3.0)
assert controls_for_size(1328, 752, 16) == dict(aspectW=16, aspectH=9, megapixels=1.0)
assert controls_for_size(1408, 2128, 16, dict(aspectW=88, aspectH=133, megapixels=2.996224)) == dict(aspectW=2, aspectH=3, megapixels=3.0)
for multiple in (8, 16, 64):
    for a, b in ((1, 1), (2, 3), (16, 9), (9, 16), (7, 5)):
        for mp in (.3, .7, 1, 1.7, 3, 6):
            requested = dict(aspectW=a, aspectH=b, megapixels=mp)
            w, h = calc_dims('%d:%d' % (a, b), mp, multiple)
            assert controls_for_size(w, h, multiple, requested) == requested
            recovered = controls_for_size(w, h, multiple)
            assert calc_dims('%d:%d' % (recovered['aspectW'], recovered['aspectH']), recovered['megapixels'], multiple) == (w, h)
# Do not use stale controls describing a different output.
assert controls_for_size(1408, 2128, 16, dict(aspectW=1, aspectH=1, megapixels=1)) == dict(aspectW=2, aspectH=3, megapixels=3.0)
# Unusual exact canvases fall back without pretending a nearby ratio is exact.
r = controls_for_size(1232, 656, 16)
assert calc_dims('%d:%d' % (r['aspectW'], r['aspectH']), r['megapixels'], 16) == (1232, 656)
print('PASS compact resolution recovery, requested controls, legacy repair and exact pixel round trips')
