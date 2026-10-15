"""Minimal ctypes binding for librtlsdr (the rtl-sdr-blog fork on top)."""

import ctypes
import ctypes.util
import os


def _load():
    names = [os.environ.get("TUNER_LIBRTLSDR"), ctypes.util.find_library("rtlsdr"),
             "librtlsdr.so.0", "/run/current-system/sw/lib/librtlsdr.so.0"]
    for name in names:
        if not name:
            continue
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    raise OSError("librtlsdr not found")


_lib = None
READ_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint32, ctypes.c_void_p)


def lib():
    global _lib
    if _lib is None:
        _lib = _load()
        p = ctypes.c_void_p
        _lib.rtlsdr_get_device_count.restype = ctypes.c_uint32
        _lib.rtlsdr_get_device_name.restype = ctypes.c_char_p
        _lib.rtlsdr_open.argtypes = [ctypes.POINTER(p), ctypes.c_uint32]
        for name in ("rtlsdr_close", "rtlsdr_reset_buffer", "rtlsdr_get_tuner_type"):
            getattr(_lib, name).argtypes = [p]
        _lib.rtlsdr_set_center_freq.argtypes = [p, ctypes.c_uint32]
        _lib.rtlsdr_get_center_freq.argtypes = [p]
        _lib.rtlsdr_get_center_freq.restype = ctypes.c_uint32
        _lib.rtlsdr_set_sample_rate.argtypes = [p, ctypes.c_uint32]
        _lib.rtlsdr_set_freq_correction.argtypes = [p, ctypes.c_int]
        _lib.rtlsdr_set_tuner_gain_mode.argtypes = [p, ctypes.c_int]
        _lib.rtlsdr_set_tuner_gain.argtypes = [p, ctypes.c_int]
        _lib.rtlsdr_get_tuner_gains.argtypes = [p, ctypes.POINTER(ctypes.c_int)]
        _lib.rtlsdr_set_agc_mode.argtypes = [p, ctypes.c_int]
        _lib.rtlsdr_read_sync.argtypes = [p, ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        _lib.rtlsdr_read_async.argtypes = [p, READ_CALLBACK, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        _lib.rtlsdr_cancel_async.argtypes = [p]
        if hasattr(_lib, "rtlsdr_set_bias_tee"):
            _lib.rtlsdr_set_bias_tee.argtypes = [p, ctypes.c_int]
    return _lib


TUNERS = {0: "unknown", 1: "E4000", 2: "FC0012", 3: "FC0013", 4: "FC2580", 5: "R820T", 6: "R828D"}


def devices():
    try:
        rtl = lib()
    except OSError:
        return []
    return [rtl.rtlsdr_get_device_name(i).decode(errors="replace")
            for i in range(rtl.rtlsdr_get_device_count())]


class Dongle:
    def __init__(self, index=0):
        self.rtl = lib()
        self.dev = ctypes.c_void_p()
        err = self.rtl.rtlsdr_open(ctypes.byref(self.dev), index)
        if err < 0:
            raise OSError("could not open the dongle (error %d); is another program using it?" % err)
        self.tuner = TUNERS.get(self.rtl.rtlsdr_get_tuner_type(self.dev), "unknown")

    def close(self):
        if self.dev:
            self.rtl.rtlsdr_close(self.dev)
            self.dev = ctypes.c_void_p()

    def gains(self):
        n = self.rtl.rtlsdr_get_tuner_gains(self.dev, None)
        if n <= 0:
            return []
        buf = (ctypes.c_int * n)()
        self.rtl.rtlsdr_get_tuner_gains(self.dev, buf)
        return [g / 10.0 for g in buf]

    def set_sample_rate(self, rate):
        self._ok(self.rtl.rtlsdr_set_sample_rate(self.dev, int(rate)), "sample rate")

    def set_center(self, freq):
        self._ok(self.rtl.rtlsdr_set_center_freq(self.dev, int(freq)), "frequency")

    def set_ppm(self, ppm):
        # Returns -2 when the value is unchanged; that is not an error.
        self.rtl.rtlsdr_set_freq_correction(self.dev, int(ppm))

    def set_gain(self, gain_db):
        """None selects the tuner's automatic gain."""
        if gain_db is None:
            self.rtl.rtlsdr_set_tuner_gain_mode(self.dev, 0)
        else:
            self.rtl.rtlsdr_set_tuner_gain_mode(self.dev, 1)
            self.rtl.rtlsdr_set_tuner_gain(self.dev, int(round(gain_db * 10)))

    def set_rtl_agc(self, on):
        self.rtl.rtlsdr_set_agc_mode(self.dev, 1 if on else 0)

    def set_bias_tee(self, on):
        if hasattr(self.rtl, "rtlsdr_set_bias_tee"):
            self.rtl.rtlsdr_set_bias_tee(self.dev, 1 if on else 0)

    def reset_buffer(self):
        self.rtl.rtlsdr_reset_buffer(self.dev)

    def read(self, nbytes):
        buf = ctypes.create_string_buffer(nbytes)
        got = ctypes.c_int()
        err = self.rtl.rtlsdr_read_sync(self.dev, buf, nbytes, ctypes.byref(got))
        if err < 0:
            raise OSError("reading from the dongle failed (error %d)" % err)
        return buf.raw[:got.value]

    def read_async(self, on_data, buffers, length):
        """Stream until cancel_async(), calling on_data(bytes) per buffer.

        libusb keeps `buffers` transfers queued in the kernel, so samples keep
        arriving while the caller is busy; read_sync loses whatever arrives
        between calls.
        """
        def callback(buf, n, ctx):
            on_data(ctypes.string_at(buf, n))

        self._callback = READ_CALLBACK(callback)  # must outlive the call
        err = self.rtl.rtlsdr_read_async(self.dev, self._callback, None, buffers, length)
        if err < 0:
            raise OSError("reading from the dongle failed (error %d)" % err)

    def cancel_async(self):
        self.rtl.rtlsdr_cancel_async(self.dev)

    @staticmethod
    def _ok(err, what):
        if err < 0:
            raise OSError("could not set the %s (error %d)" % (what, err))
