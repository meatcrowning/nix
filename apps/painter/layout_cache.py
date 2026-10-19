"""Bounded raster reuse for independently positioned layout layers (Python 2/3)."""
from collections import OrderedDict
import math


class LayerCache(object):
    def __init__(self, render, limit=32 * 1024 * 1024, scale=1):
        self.render, self.limit, self.scale = render, limit, scale
        self.entries = OrderedDict()
        self.bytes = 0
        self.misses = 0

    def size(self, svg, width, height):
        # Keys can contain embedded reference PNGs; count them as well as pixels.
        return len(svg) + int(math.ceil(width * self.scale)) * int(math.ceil(height * self.scale)) * 4

    def get(self, svg, width, height):
        key = (svg, width, height)
        if key in self.entries:
            value = self.entries.pop(key)
            self.entries[key] = value
            return value
        self.misses += 1
        value = self.render(svg, width, height)
        size = self.size(*key)
        while self.entries and self.bytes + size > self.limit:
            old, _ = self.entries.popitem(last=False)
            self.bytes -= self.size(*old)
        if size <= self.limit:
            self.entries[key] = value
            self.bytes += size
        return value
