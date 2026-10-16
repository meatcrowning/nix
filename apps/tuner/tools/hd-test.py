#!/usr/bin/env python3
"""Offline HD checks. TUNER_NRSC5 names the wrapper's library.

Optional --sample /path/to/nrsc5/support/sample.xz decodes upstream's IQ fixture.
All outputs are memory sinks; no dongle, sound server, UDP, or user files.
"""
import argparse
import ctypes as C
import lzma
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dsp
import hd
import radio


def events():
    states, frames = [], []
    d = hd.Decoder(states.append, frames.append)
    try:
        e = hd.Event(); e.event = 16; e.payload.text = b'TEST-FM'; d.event(e)
        e = hd.Event(); e.event = 2; d.event(e)
        for program in (0, 1):
            e = hd.Event(); e.event = 14; e.payload.service = hd.Service(program, 0, 5); d.event(e)
        e = hd.Event(); e.event = 8; e.payload.id3 = hd.Id3(0, b'First title', b'Artist', b'', b''); d.event(e)
        assert states[-1]['title'] == 'First title'
        d.select(1)
        assert 'title' not in states[-1] and states[-1]['channels'] == [0, 1]
        samples = np.full((2048, 2), 16384, dtype=np.int16)
        e = hd.Event(); e.event = 7
        e.payload.audio = hd.Audio(0, samples.ctypes.data_as(C.POINTER(C.c_int16)), samples.size)
        d.event(e); assert not frames
        e.payload.audio.program = 1; d.event(e)
        assert len(frames) == 1 and frames[0].shape == (2048, 2)
        assert np.all(frames[0] == .5)
        samples[:] = 0; assert np.all(frames[0] == .5), 'callback must own its audio'
        e = hd.Event(); e.event = 8; e.payload.id3 = hd.Id3(1, b'Other title', b'', b'', b''); d.event(e)
        e.payload.id3.title = b''; d.event(e); assert states[-1]['title'] == ''
        e = hd.Event(); e.event = 3; d.event(e)
        assert not states[-1]['locked'] and not states[-1]['audio'] and 'title' not in states[-1]
        d.process(bytes([127, 127]) * 10000)
    finally:
        d.close(); d.close()
    print('PASS events, channel isolation, metadata clearing, borrowed PCM ownership, pipe lifecycle')


def resampling():
    t = np.arange(44100 * 2) / 44100
    source = np.column_stack((np.sin(t*2*np.pi*1700), np.sin(t*2*np.pi*7000))).astype(np.float32)
    r = hd.Resampler()
    chunks = [r.process(source[i:i+2048]) for i in range(0, len(source), 2048)]
    out = np.concatenate(chunks)
    expected = signal.resample_poly(source, 160, 147, axis=0)[:len(out)]
    assert np.max(np.abs(expected - out)) < 1e-6
    assert 95000 < len(out) <= 96000
    print('PASS streaming resampling matches continuous 48 kHz reference across every frame boundary')


def session():
    """Paced fake capture + burst decoder and slow sink exercise the real HD loop."""
    instances, decoders, errors, states = [], [], [], []
    class Dongle:
        tuner = 'fake'
        def __init__(self, *args):
            self.cancelled = threading.Event(); self.closed = False; instances.append(self)
        def gains(self): return [0.0]
        def set_sample_rate(self, value): assert value == hd.RATE
        def set_center(self, value): self.center = value
        def set_gain(self, value): pass
        def set_ppm(self, value): pass
        def set_rtl_agc(self, value): pass
        def set_bias_tee(self, value): pass
        def reset_buffer(self): pass
        def read_async(self, callback, *args):
            while not self.cancelled.wait(.02): callback(bytes([128, 128]) * 30000)
        def cancel_async(self): self.cancelled.set()
        def close(self): self.closed = True
    class Decoder:
        def __init__(self, metadata, audio, program):
            self.metadata, self.audio, self.program = metadata, audio, program
            self.state = {'locked': True, 'station': 'TEST', 'program': program, 'channels': [0, 1]}
            self.n = 0; self.closed = False; decoders.append(self)
        def process(self, raw):
            self.n += 1
            if self.n % 4 == 0:
                for _ in range(2): self.audio(np.full((2048, 2), .25 + self.program*.25, np.float32))
        def select(self, program): self.program = program; self.state['program'] = program; self._publish()
        def _publish(self): self.metadata(dict(self.state))
        def close(self): self.closed = True
    class Sink:
        def __init__(self): self.frames = []; self.closed = False
        def write(self, frames): self.frames.append(frames.copy()); time.sleep(len(frames)/48000)
        def close(self): self.closed = True
        def set_target(self, value): pass
    rx = dict(dsp.Receiver.DEFAULTS, volume_db=0)
    r = radio.Radio(rx, lambda *a: None, lambda *a: None, errors.append, lambda: None)
    r.on_hd = lambda generation, data: states.append((generation, dict(data)))
    sink = r.playback = Sink()
    def until(predicate):
        limit = time.monotonic()+5
        while not predicate() and time.monotonic() < limit: time.sleep(.02)
        assert predicate(), (errors, len(sink.frames))
    with patch('hdreceiver.rtl.Dongle', Dongle), patch('hdreceiver.hd.Decoder', Decoder):
        r.start({'frequency': 106300000, 'sample_rate': 1920000, 'hd': True})
        try:
            until(lambda: len(sink.frames) >= 4)
            r.select_hd(1)
            until(lambda: sink.frames and abs(float(sink.frames[-1][100,0])-.5) < .01)
            rx['mute'] = True
            until(lambda: np.max(np.abs(sink.frames[-1])) == 0)
            old = r.metadata_generation; r.tune(102700000)
            until(lambda: len(decoders) == 2 and any(g > old for g, _ in states))
            assert instances[0].center == 102700000
            assert decoders[0].closed
            assert r.dropped == 0
        finally:
            r.stop(); r.thread.join(5)
        assert not r.thread.is_alive() and not errors, errors
        assert instances[0].closed and sink.closed and decoders[-1].closed
    print('PASS burst audio, mute, channel switch, retune generation, zero capture drops, clean shutdown')


def sample(path):
    for program in (0, 1):
        states, audio = [], []
        d = hd.Decoder(states.append, audio.append, program)
        try:
            with lzma.open(path, 'rb') as stream:
                while raw := stream.read(196608): d.process(raw)
        finally:
            d.close()
        assert audio and any(s.get('station') == 'KUT' for s in states)
        assert any(s.get('channels') == [0, 1] for s in states)
        if program == 0:
            assert any(s.get('title') for s in states)
        else:
            assert not any(s.get('title') for s in states), 'HD1 title leaked into HD2'
        assert all(f.shape[1] == 2 for f in audio)
        print('PASS upstream IQ fixture HD%d: %d decoded stereo frames, station and channels' %
              (program+1, sum(map(len, audio))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--sample'); args = parser.parse_args()
    events(); resampling(); session()
    if args.sample: sample(args.sample)
