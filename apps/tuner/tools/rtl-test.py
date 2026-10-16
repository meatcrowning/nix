#!/usr/bin/env python3
"""Fake driver regression: a tune may reset RF gain. Never opens USB."""
import ctypes
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rtl

class Driver:
    def __init__(self):
        self.gain = 0
        self.manual = False
        self.fail = False
    def rtlsdr_set_center_freq(self, device, frequency):
        self.gain, self.manual = 0, False
        return 0
    def rtlsdr_set_tuner_gain_mode(self, device, manual):
        self.manual = bool(manual)
        return 0
    def rtlsdr_set_tuner_gain(self, device, gain):
        if self.fail:
            return -1
        self.gain = gain
        return 0

d = rtl.Dongle.__new__(rtl.Dongle)
d.dev, d.rtl, d.gain_db = ctypes.c_void_p(), Driver(), None
for gain in (24.8, 9.9, 0, None):
    d.set_gain(gain)
    for freq in (106300000, 5000000, 102700000):
        d.set_center(freq)
        assert d.rtl.manual == (gain is not None)
        if gain is not None:
            assert d.rtl.gain == round(gain*10)
d.set_gain(9.9); d.rtl.fail = True
try:
    d.set_center(106300000)
except OSError as exc:
    assert 'gain' in str(exc)
else:
    raise AssertionError('RF gain failure was silently ignored')
assert d.gain_db == 9.9
print('PASS manual/automatic RF gain survives tuner reinitialization; driver errors surface')
