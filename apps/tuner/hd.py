"""nrsc5 pipe decoder. No device or audio access; called on the radio worker.

The ctypes structures describe only the event prefixes we consume from
nrsc5.h (3.2 API); callbacks copy all borrowed data before returning.
"""
import ctypes as C
import os
import time

import numpy as np
from scipy import signal

RATE = 1488375


class Audio(C.Structure):
    _fields_ = [('program', C.c_uint), ('data', C.POINTER(C.c_int16)), ('count', C.c_size_t)]


class Id3(C.Structure):
    _fields_ = [('program', C.c_uint), ('title', C.c_char_p), ('artist', C.c_char_p),
                ('album', C.c_char_p), ('genre', C.c_char_p)]


class Service(C.Structure):
    _fields_ = [('program', C.c_uint), ('access', C.c_uint), ('type', C.c_uint)]


class Mer(C.Structure):
    _fields_ = [('lower', C.c_float), ('upper', C.c_float)]


class Payload(C.Union):
    _fields_ = [('audio', Audio), ('id3', Id3), ('service', Service),
                ('text', C.c_char_p), ('mer', Mer)]


class Event(C.Structure):
    _fields_ = [('event', C.c_uint), ('payload', Payload)]


Callback = C.CFUNCTYPE(None, C.POINTER(Event), C.c_void_p)


def text(value):
    return ' '.join((value or b'').decode('utf-8', 'replace').split())[:512]


class Resampler:
    """44.1 -> 48 kHz with overlap on both sides, aligned to rational phases."""
    def __init__(self):
        self.history = np.zeros((294, 2), np.float32)
        self.pending = np.empty((0, 2), np.float32)

    def process(self, frames):
        self.pending = np.concatenate((self.pending, frames))
        count = max(0, (len(self.pending) - 294) // 147 * 147)
        if not count:
            return np.empty((0, 2), np.float32)
        data = np.concatenate((self.history, self.pending[:count + 294]))
        out = signal.resample_poly(data, 160, 147, axis=0)[320:320 + count * 160 // 147]
        self.history = data[count:count + 294].copy()
        self.pending = self.pending[count:]
        return out.astype(np.float32)


class Decoder:
    def __init__(self, on_metadata, on_audio, program=0):
        self.lib = C.CDLL(os.environ.get('TUNER_NRSC5', 'libnrsc5.so'))
        self.lib.nrsc5_open_pipe.argtypes = [C.POINTER(C.c_void_p)]
        self.lib.nrsc5_open_pipe.restype = C.c_int
        self.lib.nrsc5_set_callback.argtypes = [C.c_void_p, Callback, C.c_void_p]
        self.lib.nrsc5_set_callback.restype = None
        self.lib.nrsc5_pipe_samples_cu8.argtypes = [C.c_void_p, C.c_void_p, C.c_uint]
        self.lib.nrsc5_pipe_samples_cu8.restype = C.c_int
        self.lib.nrsc5_close.argtypes = [C.c_void_p]
        self.lib.nrsc5_close.restype = None
        self.on_metadata, self.on_audio = on_metadata, on_audio
        self.handle = C.c_void_p()
        self.program = max(0, min(7, int(program)))
        self.state = {'locked': False, 'program': self.program, 'channels': [], 'station': ''}
        self.tags = {}
        self.channels = set()
        self.last_audio = 0.0
        self.error = None
        self.last_state = None
        self.callback = Callback(self._callback)
        if self.lib.nrsc5_open_pipe(C.byref(self.handle)):
            raise OSError('Could not initialize HD Radio decoder')
        self.lib.nrsc5_set_callback(self.handle, self.callback, None)

    def select(self, program):
        self.program = max(0, min(7, int(program)))
        self.last_audio = 0.0
        self._publish()

    def _publish(self):
        data = dict(self.state, program=self.program, channels=sorted(self.channels))
        data.update(self.tags.get(self.program, {}))
        data['audio'] = time.monotonic() - self.last_audio < 2
        if data != self.last_state:
            self.last_state = data
            self.on_metadata(data)

    def _callback(self, pointer, opaque):
        try:
            self.event(pointer.contents)
        except Exception as exc:
            # ctypes otherwise only prints callback errors and keeps receiving.
            self.error = exc

    def event(self, event):
        kind, p = event.event, event.payload
        if kind == 2:  # SYNC
            self.state['locked'] = True
        elif kind == 3:  # LOST_SYNC
            self.state['locked'] = False
            self.last_audio = 0.0
            self.tags.clear()
            self.state.pop('mer', None)
        elif kind == 4:  # MER
            self.state['mer'] = (float(p.mer.lower), float(p.mer.upper))
        elif kind in (14, 20):  # AUDIO_SERVICE, AUDIO_SERVICE_DESCRIPTOR
            if p.service.program < 8 and p.service.access == 0:
                self.channels.add(p.service.program)
        elif kind == 16:  # STATION_NAME
            self.state['station'] = text(p.text)
        elif kind == 8:  # ID3 (including empty tags, which clear the old title)
            if p.id3.program >= 8:
                return
            self.tags[p.id3.program] = {key: text(getattr(p.id3, key))
                                       for key in ('title', 'artist', 'album', 'genre')}
        elif kind == 7:  # AUDIO: count is interleaved int16 samples, not frames
            a = p.audio
            if a.program >= 8:
                return
            new_channel = a.program not in self.channels
            self.channels.add(a.program)
            if a.program == self.program and a.data and 0 < a.count <= 16384 and a.count % 2 == 0:
                fresh = time.monotonic() - self.last_audio >= 2
                self.last_audio = time.monotonic()
                frames = np.ctypeslib.as_array(a.data, shape=(a.count,)).copy().reshape(-1, 2)
                self.on_audio(frames.astype(np.float32) / 32768)
                if not fresh and not new_channel:
                    return
            elif not new_channel:
                return
        else:
            return
        self._publish()

    def process(self, raw):
        if self.lib.nrsc5_pipe_samples_cu8(self.handle, raw, len(raw)):
            raise OSError('HD Radio decoder rejected IQ samples')
        if self.error:
            raise OSError('HD Radio callback failed: %s' % self.error)

    def close(self):
        if self.handle:
            self.lib.nrsc5_close(self.handle)
            self.handle = C.c_void_p()
