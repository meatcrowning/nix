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


def attention_weights(q, k, heads, image_count, chunk_size=64):
    """Image-query/text-key probabilities, normalized over every image/text key.

    Query chunks bound temporary logits; never materialize the full N-by-N
    attention matrix. Import torch only in the backend, not the Qt frontend.
    """
    import torch
    batch, length, channels = q.shape
    dim = channels // heads
    queries = q.reshape(batch, length, heads, dim).transpose(1, 2).float()
    keys = k.reshape(batch, length, heads, dim).transpose(1, 2).float()
    chunk_size = min(chunk_size, max(1, (32 * 1024 * 1024) // (batch * heads * length * 4)))
    maps = torch.empty((batch, length-image_count, image_count), device=q.device, dtype=torch.float32)
    for start in range(0, image_count, chunk_size):
        end = min(image_count, start+chunk_size)
        scores = queries[:, :, start:end] @ keys.transpose(-1, -2)
        scores.mul_(dim ** -0.5)
        probabilities = scores.softmax(dim=-1)
        maps[:, :, start:end] = probabilities[..., image_count:].mean(1).transpose(1, 2)
    return maps
