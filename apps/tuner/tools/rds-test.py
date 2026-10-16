#!/usr/bin/env python3
"""Offline RDS checks: synthetic FM IQ -> Receiver MPX -> real Redsea -> metadata.

Use TUNER_REDSEA=/path/to/redsea with tuner's Python interpreter. No dongle,
audio device, GUI, network, or user configuration is accessed.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
import threading

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dsp
import rds
import radio


def block(data, offset):
    word = data << 10
    remainder = word
    for bit in range(25, 9, -1):
        if remainder & (1 << bit):
            remainder ^= 0x5B9 << (bit - 10)
    return f'{word | (remainder ^ offset):026b}'


def multiplex(pi=0x1234, ps='TEST FM ', text='RDS PIPELINE TEST', version_b=False):
    # Standard 0A/0B PS and 2A/2B RadioText, including a carriage-return terminator.
    groups = []
    for part in range(4):
        groups.append((pi, (0x800 if version_b else 0) | part,
                       pi if version_b else 0, int.from_bytes(ps[part*2:part*2+2].encode(), 'big')))
    size = 2 if version_b else 4
    message = (text + '\r').ljust(64 if not version_b else 32)
    for part in range((len(text) + size) // size):
        chunk = message[part*size:part*size+size].encode()
        groups.append((pi, (0x2800 if version_b else 0x2000) | part,
                       pi if version_b else int.from_bytes(chunk[:2], 'big'),
                       int.from_bytes(chunk[-2:], 'big')))
    offsets = (0xFC, 0x198, 0x350 if version_b else 0x168, 0x1B4)
    bits = ''.join(block(word, off) for group in groups * 10 for word, off in zip(group, offsets))
    differential = np.bitwise_xor.accumulate(np.fromiter(map(int, bits), dtype=np.uint8))
    symbols = np.column_stack((1.0 - 2*differential.astype(float), 2*differential.astype(float) - 1)).ravel()
    rate = dsp.WIDE_RATE
    t = np.arange(int(len(symbols) * rate / 2375)) / rate
    base = symbols[np.minimum((t * 2375).astype(int), len(symbols)-1)]
    shaped = signal.lfilter(signal.firwin(151, 2400, fs=rate), [1.0], base)
    return (.20*np.sin(2*np.pi*1000*t) + .08*np.cos(2*np.pi*19000*t)
            + .06*shaped*np.cos(2*np.pi*57000*t)).astype(np.float32)


def decode_pcm(mpx):
    pcm = (np.clip(mpx, -1, 1)*32767).astype('<i2').tobytes()
    run = subprocess.run([os.environ['TUNER_REDSEA'], '-i', 'mpx', '-r', '240000'],
                         input=pcm, capture_output=True, check=True, timeout=30)
    return [json.loads(line) for line in run.stdout.splitlines()]


def main():
    mpx = multiplex()
    rate = 960000
    wide = signal.resample_poly(mpx, 4, 1)
    phase = np.cumsum(wide * (2*np.pi*75000/rate))
    phase += 2*np.pi*30000*np.arange(len(wide))/rate
    iq = np.exp(1j*phase).astype(np.complex64)
    del wide, phase
    for mode in dsp.WFM_MODES:
        rx = dsp.Receiver(rate, {'mode': mode, 'offset': 30000, 'mute': True, 'squelch_db': 10})
        taps = []
        for i in range(0, len(iq), 98304):
            audio = rx.process(iq[i:i+98304])
            assert not np.any(audio), 'test audio must remain muted'
            taps.append(rx.last_mpx.copy())
        decoded = decode_pcm(np.concatenate(taps))
        assert any(g.get('ps', '').strip() == 'TEST FM' for g in decoded), decoded[-5:]
        assert any(g.get('radiotext') == 'RDS PIPELINE TEST' for g in decoded), decoded[-5:]
        rx.set(mode='AM', filter_low=-5000, filter_high=5000)
        rx.process(iq[:98304])
        assert rx.last_mpx is None
        print('PASS', mode, 'FM IQ -> pre-audio MPX -> PS and RadioText (muted and squelched)')
    decoded = decode_pcm(multiplex(version_b=True))
    assert any(g.get('ps', '').strip() == 'TEST FM' for g in decoded)
    assert any(g.get('radiotext') == 'RDS PIPELINE TEST' for g in decoded)
    print('PASS 0B/2B groups')

    meta = rds.Metadata()
    assert meta.update({'pi':'0x1234','ps':'TEST FM','radiotext':'OLD','rt_ab':'A'})['radiotext']=='OLD'
    assert 'radiotext' not in meta.update({'pi':'0x1234','rt_ab':'B'})
    assert 'ps' not in meta.update({'pi':'0x5678'})
    assert meta.update({'pi':'garbage'}) is None
    assert meta.update([]) is None
    events=[]
    decoder=rds.Decoder(lambda gen,data: events.append((gen,data)), generation=1)
    try:
        for i in range(0,len(mpx),12000):
            decoder.submit(mpx[i:i+12000],1)
            time.sleep(.05)
        limit=time.monotonic()+2
        while not any(d.get('radiotext')=='RDS PIPELINE TEST' for _,d in events) and time.monotonic()<limit:
            time.sleep(.02)
        assert any(d.get('ps')=='TEST FM' for _,d in events), events[-5:]
        assert any(d.get('radiotext')=='RDS PIPELINE TEST' for _,d in events), events[-5:]
        decoder.reset(2)
        decoder.submit(mpx[:12000],1)  # stale producer
        time.sleep(.1)
        assert events[-1] == (2, {}), events[-3:]
        mark=len(events)
        time.sleep(.1)
        assert not any(gen==1 for gen,_ in events[mark:])
    finally:
        decoder.close()
    assert not decoder.thread.is_alive()
    errors=[]
    decoder=rds.Decoder(lambda gen,data: errors.append(data), executable='/nonexistent/redsea')
    try:
        decoder.submit(mpx[:12000],0)
        limit=time.monotonic()+2
        while not any(d.get('error') for d in errors) and time.monotonic()<limit:
            time.sleep(.02)
        assert any(d.get('error') for d in errors)
    finally:
        decoder.close()
    print('PASS non-blocking bridge, generation reset, text A/B, PI change, missing decoder, teardown')

    # Exercise Radio's real producer/consumer wiring with a synthetic dongle
    # and a counting sink. Neither the USB library nor pw-cat is invoked.
    rotation = np.exp(2j*np.pi*(rate/4-30000)*np.arange(len(iq))/rate).astype(np.complex64)
    raw = np.clip((iq*rotation*.6).view(np.float32)*128+127.4,0,255).astype(np.uint8).tobytes()
    cancel = threading.Event()
    class Dongle:
        tuner = 'synthetic'
        def __init__(self, device): pass
        def gains(self): return []
        def set_sample_rate(self, value): assert value == rate
        def set_ppm(self, value): pass
        def set_rtl_agc(self, value): pass
        def set_gain(self, value): pass
        def set_bias_tee(self, value): pass
        def set_center(self, value): pass
        def reset_buffer(self): pass
        def close(self): cancel.set()
        def cancel_async(self): cancel.set()
        def read_async(self, callback, *args):
            for i in range(0,len(raw),radio.READ_BYTES):
                if cancel.is_set(): break
                callback(raw[i:i+radio.READ_BYTES])
                cancel.wait(radio.READ_BYTES/(2*rate))
            cancel.wait(15)
    class Sink:
        frames = 0
        def write(self, frames): self.frames += len(frames)
        def close(self): pass
    found, stopped = threading.Event(), threading.Event()
    errors=[]
    receiver=radio.Radio({'mode':'WFM (stereo)'},lambda *a:None,lambda *a:None,errors.append,stopped.set)
    receiver.playback=Sink()
    receiver.on_rds=lambda gen,data: found.set() if data.get('radiotext')=='RDS PIPELINE TEST' else None
    with patch.object(radio.rtl,'Dongle',Dongle):
        try:
            receiver.start({'frequency':102700000,'sample_rate':rate})
            assert found.wait(15), errors
        finally:
            receiver.stop()
            assert stopped.wait(4), 'radio worker did not stop'
            receiver.thread.join(1)
    assert not errors and receiver.playback.frames>0
    assert receiver.rds is None and not receiver.thread.is_alive()
    print('PASS synthetic dongle -> radio worker -> RDS callback, concurrent audio, stop cleanup')


if __name__=='__main__':
    main()
