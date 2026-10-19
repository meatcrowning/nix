"""Resolution controls shared by modern Qt and the Python 2.7 GTK adapter."""
from __future__ import division
import math


def calc_dims(aspect, megapixels, multiple=64):
    """Width/height for an aspect ratio at a target pixel count."""
    try:
        aw, ah = (float(x) for x in str(aspect).split(":"))
    except ValueError:
        aw = ah = 1.0
    total = max(megapixels, 0.05) * 1000000

    h = math.sqrt(total * ah / aw)
    w = h * aw / ah
    q = max(int(multiple), 1)
    def quantize(value):
        # Python 2's round() breaks half ties differently from the Qt engine.
        units = value / q
        lower = int(math.floor(units))
        fraction = units - lower
        upper = fraction > .5 or (fraction == .5 and lower % 2)
        return max(q, (lower + int(bool(upper))) * q)
    return quantize(w), quantize(h)


def controls_for_size(width, height, multiple=64, preferred=None):
    """Recover compact controls only when they reproduce the same rounded pixels."""
    width, height = int(width), int(height)
    preferred = preferred or {}
    def matches(aw, ah, mp):
        return calc_dims('%s:%s' % (aw, ah), mp, multiple) == (width, height)
    try:
        aw, ah = int(preferred.get('aspectW', 0)), int(preferred.get('aspectH', 0))
        mp = float(preferred.get('megapixels', 0))
        if math.isnan(mp) or math.isinf(mp): mp = 0
    except (TypeError, ValueError, OverflowError):
        aw = ah = mp = 0
    if aw > 0 and ah > 0 and mp > 0 and matches(aw, ah, mp):
        # Keep intentional small ratios/budgets exactly as entered. Old derived
        # fractions and pixel-area tails are eligible for lossless simplification.
        if max(aw, ah) <= 32 and abs(mp - round(mp, 3)) < 1e-9:
            return dict(aspectW=aw, aspectH=ah, megapixels=mp)
    area = width * height / 1000000
    common = [(1, 1), (2, 3), (3, 2), (3, 4), (4, 3), (4, 5), (5, 4),
              (9, 16), (16, 9), (1, 2), (2, 1), (5, 8), (8, 5), (9, 21), (21, 9)]
    ratios = common + sorted(((a, b) for a in range(1, 33) for b in range(1, 33)),
                    key=lambda pair: (sum(pair), abs(pair[0] / pair[1] - width / height)))
    for digits in (1, 2, 3):
        budget = round(area, digits)
        if budget <= 0: continue
        for a, b in ratios:
            if matches(a, b, budget):
                return dict(aspectW=a, aspectH=b, megapixels=budget)
    # Exact pixel ratios remain necessary for unusual custom canvases.
    a, b = width, height
    while b: a, b = b, a % b
    return dict(aspectW=width // a, aspectH=height // a, megapixels=area)
