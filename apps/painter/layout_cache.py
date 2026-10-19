"""Bounded raster reuse for independently positioned layout layers (Python 2/3)."""
from collections import OrderedDict
import math


class LayerCache(object):
    def __init__(self, render, limit=32 * 1024 * 1024, scale=1):
        self.render, self.limit, self.scale = render, limit, scale
        self.entries = OrderedDict()
        self.bytes = 0
        self.misses = 0

    def size(self, width, height):
        return int(math.ceil(width * self.scale)) * int(math.ceil(height * self.scale)) * 4

    def get(self, svg, width, height):
        key = (svg, width, height)
        if key in self.entries:
            value = self.entries.pop(key)
            self.entries[key] = value
            return value
        self.misses += 1
        value = self.render(svg, width, height)
        size = self.size(width, height)
        while self.entries and self.bytes + size > self.limit:
            old, _ = self.entries.popitem(last=False)
            self.bytes -= self.size(old[1], old[2])
        if size <= self.limit:
            self.entries[key] = value
            self.bytes += size
        return value
