"""Sampler-callback capture window, independent of guidance/evaluation counts."""
class CaptureWindow:
    def __init__(self, steps):
        self.steps = steps
        self.step = 0
        self.pending = None
        self.maps = None
        self.captured = []

    @property
    def wanted(self):
        start = self.steps // 4
        span = max(1, 2*self.steps//3 - self.steps//3)
        return start <= self.step < start + span and (self.step-start) % 3 == 0

    def begin(self):
        # A corrector or guidance evaluation may precede the predictor. Only
        # the last positive evaluation before the sampler callback is retained.
        self.pending = None

    def finish(self, step):
        if step == self.step and self.wanted and self.pending is not None:
            if self.maps is None:
                self.maps = self.pending
            else:
                self.maps.add_(self.pending)
            self.captured.append(step)
        self.pending = None
        self.step = step + 1


def map_shape(height, width, tokens):
    """Keep native detail up to 128, reserving storage for bounded metadata."""
    height, width = min(height, 128), min(width, 128)
    budget = 20 * 1024 * 1024
    if height * width * tokens > budget:
        scale = (budget / (height * width * tokens)) ** .5
        height, width = max(1, int(height * scale)), max(1, int(width * scale))
    return height, width
