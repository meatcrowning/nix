"""Reference sampling interval, including migration from the three presets."""
import math


def interval(params):
    phase = params.get('reference_phase', 'early')
    if phase not in ('early', 'middle', 'late'):
        raise ValueError('Invalid reference phase')
    index = ('early', 'middle', 'late').index(phase)
    start = float(params.get('reference_start', index / 3.0))
    end = float(params.get('reference_end', (index + 1) / 3.0))
    finite = all(not math.isnan(value) and not math.isinf(value) for value in (start, end))
    if not (finite and 0 <= start <= end <= 1):
        raise ValueError('Reference range requires 0 <= start <= end <= 1')
    return dict(reference_start=start, reference_end=end)
