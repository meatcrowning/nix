# -*- coding: utf-8 -*-
"""Token decorations derived from editor colours; usable by Qt and GTK 3.6."""
from __future__ import division


def colours(text, background, selection):
    def blend(amount):
        return tuple(round(b + (f - b) * amount) for f, b in zip(text, background))

    def luminance(rgb):
        values = [v / 255 for v in rgb]
        return sum(w * (v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4)
                   for w, v in zip((.2126, .7152, .0722), values))

    def contrast(a, b):
        x, y = sorted((luminance(a), luminance(b)))
        return (y + .05) / (x + .05)

    bands = [blend(.07), blend(.14)]
    # Choose a saturated separator distinct from text, selection and both
    # bands. These are local annotations, not overrides of the native palette.
    candidates = [(0, 145, 155), (185, 85, 195), (210, 120, 0),
                  (65, 110, 220), (20, 150, 70), (215, 65, 95),
                  (80, 205, 210), (225, 150, 245), (245, 185, 55)]
    references = [text, background, selection] + bands
    def score(rgb):
        distance = min(sum((a - b) ** 2 for a, b in zip(rgb, ref)) for ref in references)
        return (min(contrast(rgb, background), 3), distance)
    separator = max(candidates, key=score)
    def hex_colour(rgb):
        return '#%02x%02x%02x' % tuple(int(v) for v in rgb)
    return dict(bands=[hex_colour(v) for v in bands], separator=hex_colour(separator))
