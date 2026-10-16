"""Receiver DSP: complex baseband from the dongle in, 48 kHz stereo out.

Pure numpy/scipy so it can be driven offline from a recorded IQ file
(tools/dsp-test.py). Every stage keeps its own history, so blocks of any
length join without clicks.

Rates: input fs (a multiple of 240 kHz) -> 240 kHz (WFM channel) -> 48 kHz
(narrow channels and all audio).
"""

import math
import threading

import numpy as np
from scipy import signal

AUDIO_RATE = 48000
WIDE_RATE = 240000

MODES = ["AM", "AM-Sync", "Narrow FM", "WFM (mono)", "WFM (stereo)",
         "LSB", "USB", "CW-L", "CW-U"]
WFM_MODES = ("WFM (mono)", "WFM (stereo)")
# gqrx names a few modes we fold into the closest one we implement.
MODE_ALIASES = {"WFM (oirt)": "WFM (mono)", "Raw I/Q": "USB", "Demod Off": "AM"}

# (low cut, high cut) in Hz relative to the tuned frequency, as gqrx's
# Wide / Normal / Narrow presets.
FILTER_PRESETS = {
    "AM":           [(-10000, 10000), (-5000, 5000), (-2500, 2500)],
    "AM-Sync":      [(-10000, 10000), (-5000, 5000), (-2500, 2500)],
    "Narrow FM":    [(-10000, 10000), (-5000, 5000), (-2500, 2500)],
    "WFM (mono)":   [(-100000, 100000), (-80000, 80000), (-60000, 60000)],
    "WFM (stereo)": [(-100000, 100000), (-80000, 80000), (-60000, 60000)],
    "LSB":          [(-4000, -100), (-2800, -100), (-2400, -300)],
    "USB":          [(100, 4000), (100, 2800), (300, 2400)],
    "CW-L":         [(-500, 500), (-250, 250), (-100, 100)],
    "CW-U":         [(-500, 500), (-250, 250), (-100, 100)],
}
FILTER_WIDTHS = ["Wide", "Normal", "Narrow", "User"]
FILTER_SHAPES = {"Soft": 0.35, "Normal": 0.2, "Sharp": 0.08}  # transition / width

# Decay (ms) and hang for gqrx's AGC presets; None means manual gain.
AGC_PRESETS = {"Fast": (100, False), "Medium": (500, False), "Slow": (2000, True),
               "User": None, "Off": None}

STEREO_PILOT_MIN = 0.02  # pilot amplitude, as a fraction of 75 kHz deviation


def canonical_mode(name):
    name = MODE_ALIASES.get(name, name)
    return name if name in MODES else "AM"


def filter_for(mode, width, low=None, high=None):
    if width == "User" and low is not None and high is not None:
        return low, high
    index = {"Wide": 0, "Normal": 1, "Narrow": 2}.get(width, 1)
    return FILTER_PRESETS[mode][index]


def bookmark_filter(mode, bandwidth):
    """gqrx bookmarks store one bandwidth; turn it back into low/high cuts."""
    if not bandwidth:
        return filter_for(mode, "Normal")
    if mode == "USB":
        return 100, 100 + bandwidth
    if mode == "LSB":
        return -100 - bandwidth, -100
    return -bandwidth // 2, bandwidth // 2


def lowpass(rate, cutoff, transition):
    taps = signal.firwin(_odd(4.0 * rate / transition), cutoff, fs=rate)
    return taps.astype(np.float32)


def _odd(n):
    n = int(math.ceil(n))
    n = max(n, 15)
    return n | 1


class FirDecimator:
    """Streaming FIR filter with decimation, complex or real input."""

    def __init__(self, taps, factor):
        self.taps = taps
        self.factor = factor
        self.history = None
        self.phase = 0

    def __call__(self, x):
        if self.history is None or self.history.dtype != x.dtype:
            self.history = np.zeros(len(self.taps) - 1, dtype=x.dtype)
        data = np.concatenate((self.history, x))
        self.history = data[len(data) - (len(self.taps) - 1):]
        if self.factor == 1:
            return signal.oaconvolve(data, self.taps, mode="valid").astype(x.dtype)
        # Only every factor-th output is needed; filter the polyphase way by
        # convolving the full stream (FFT based, cheap) and striding.
        full = signal.oaconvolve(data, self.taps, mode="valid")
        out = full[self.phase::self.factor]
        self.phase = (self.phase - len(x)) % self.factor
        return out.astype(x.dtype)


class Nco:
    """Phase-continuous complex mixer."""

    def __init__(self, rate):
        self.rate = rate
        self.freq = 0.0
        self.phase = 0.0

    def __call__(self, x, freq=None):
        if freq is not None:
            self.freq = freq
        if self.freq == 0:
            return x
        step = -2 * math.pi * self.freq / self.rate
        ph = self.phase + step * np.arange(len(x), dtype=np.float64)
        self.phase = (self.phase + step * len(x)) % (2 * math.pi)
        return x * np.exp(1j * ph).astype(np.complex64)


class Iir:
    """Streaming lfilter wrapper."""

    def __init__(self, b, a):
        self.b, self.a = b, a
        self.zi = None

    def __call__(self, x):
        if self.zi is None:
            self.zi = np.zeros(max(len(self.a), len(self.b)) - 1)
        # lfilter hands the state back as float64 whatever x is; keep it, or
        # every block restarts from zero and clicks.
        y, self.zi = signal.lfilter(self.b, self.a, x, zi=self.zi.astype(np.result_type(x, self.zi)))
        return y.astype(x.dtype)


def deemphasis(rate, tau_us):
    if not tau_us:
        return None
    alpha = 1 - math.exp(-1.0 / (rate * tau_us * 1e-6))
    return Iir(np.array([alpha]), np.array([1.0, alpha - 1.0]))


class QuadDemod:
    def __init__(self):
        self.last = np.complex64(0)

    def __call__(self, x):
        prev = np.concatenate(([self.last], x[:-1]))
        self.last = x[-1]
        return np.angle(x * np.conj(prev)).astype(np.float32)


class PhaseTracker:
    """Absolute phase of a carrier near a known frequency.

    Mixing the carrier to DC and averaging over `window` samples gives its
    phasor; the windows are joined into a per-sample, unwrapped phase and the
    mixer's own rotation is added back, so cos(phase) reproduces the carrier.
    Used for the 19 kHz stereo pilot and for AM-Sync's carrier.
    """

    def __init__(self, rate, freq, window):
        self.omega = 2 * math.pi * freq / rate
        self.window = window
        self.count = 0  # samples seen, for the mixer's phase
        self.tail = np.zeros(0, dtype=np.complex64)
        self.last_phase = 0.0
        self.level = 0.0

    def __call__(self, x):
        rotation = self.omega * (self.count + np.arange(len(x), dtype=np.float64))
        self.count = (self.count + len(x)) % 10_000_000_000
        mixed = (x * np.exp(-1j * rotation)).astype(np.complex64)
        data = np.concatenate((self.tail, mixed))
        n = len(data) // self.window
        if n == 0:
            self.tail = data
            return rotation + self.last_phase, self.level
        blocks = data[:n * self.window].reshape(n, self.window).mean(axis=1)
        carried = len(self.tail)
        self.tail = data[n * self.window:]
        phases = np.unwrap(np.concatenate(([self.last_phase], np.angle(blocks))))
        centres = (np.arange(n) + 0.5) * self.window - carried
        smooth = np.interp(np.arange(len(x)),
                           np.concatenate(([centres[0] - self.window], centres)), phases)
        self.last_phase = float(phases[-1]) % (2 * math.pi)
        self.level = float(np.abs(blocks).mean())
        return rotation + smooth, self.level


class Agc:
    """Envelope AGC run in 5 ms chunks, with gqrx's decay/hang/slope knobs."""

    CHUNK = AUDIO_RATE // 200

    def __init__(self):
        self.gain = 1.0
        self.peak = 1e-6
        self.hang_left = 0

    def __call__(self, x, decay_ms, hang, threshold_db, slope_db, target=0.3):
        out = np.empty_like(x)
        decay = math.exp(-self.CHUNK / (AUDIO_RATE * max(decay_ms, 10) / 1000.0))
        max_gain = 10 ** (-threshold_db / 20.0)
        for start in range(0, len(x), self.CHUNK):
            chunk = x[start:start + self.CHUNK]
            peak = float(np.max(np.abs(chunk))) if len(chunk) else 0.0
            if peak > self.peak:
                self.peak = peak  # instant attack
                self.hang_left = 25 if hang else 0  # 125 ms
            elif self.hang_left > 0:
                self.hang_left -= 1
            else:
                self.peak = max(peak, self.peak * decay, 1e-9)
            want = min(target / self.peak, max_gain)
            # Slope: how much louder strong signals are allowed to be, in dB
            # per 10 dB above the knee, like gqrx's.
            if slope_db and want < max_gain:
                over = 20 * math.log10(max_gain / want)
                want *= 10 ** (over * slope_db / 10 / 20)
            ramp = np.linspace(self.gain, want, len(chunk), endpoint=False, dtype=np.float32)
            out[start:start + self.CHUNK] = chunk * ramp
            self.gain = want
        return out


class Receiver:
    """Holds the settings and the stages built from them.

    The GUI writes settings with set(); the radio thread calls process().
    """

    DEFAULTS = {
        "mode": "WFM (stereo)",
        "offset": 0.0,  # tuned frequency minus the dongle's centre, Hz
        "filter_width": "Normal",
        "filter_low": -80000,
        "filter_high": 80000,
        "filter_shape": "Normal",
        "squelch_db": -150.0,
        "agc": "Medium",
        "agc_threshold_db": -100.0,
        "agc_decay_ms": 500,
        "agc_slope_db": 0.0,
        "agc_hang": False,
        "agc_manual_gain_db": 0.0,
        "nb1": False,
        "nb1_threshold": 3.3,
        "nb2": False,
        "nb2_threshold": 2.5,
        "fm_max_dev": 5000,
        "nfm_tau_us": 75,
        "wfm_tau_us": 75,
        "am_dcr": True,
        "cw_offset": 700,
        "volume_db": -6.0,
        "mute": False,
    }

    def __init__(self, input_rate, settings=None):
        if input_rate % WIDE_RATE:
            raise ValueError("input rate must be a multiple of 240 kHz")
        self.input_rate = input_rate
        self.s = dict(self.DEFAULTS)
        if settings:
            self.s.update({k: v for k, v in settings.items() if k in self.DEFAULTS})
        self.s["mode"] = canonical_mode(self.s["mode"])
        self.lock = threading.Lock()
        self.dirty = True
        self.level_db = -150.0
        self.stereo = False
        self.squelched = False
        self.last_mpx = None

    def set(self, **changes):
        with self.lock:
            for key, value in changes.items():
                if key not in self.DEFAULTS:
                    raise KeyError(key)
                if key == "mode":
                    value = canonical_mode(value)
                self.s[key] = value
            if set(changes) - {"offset", "squelch_db", "volume_db", "mute", "agc_threshold_db",
                               "agc_decay_ms", "agc_slope_db", "agc_hang", "agc_manual_gain_db",
                               "agc", "nb1_threshold", "nb2_threshold", "nb1", "nb2"}:
                self.dirty = True

    def _build(self):
        s = self.s
        mode = s["mode"]
        self.nco = Nco(self.input_rate)
        down1 = self.input_rate // WIDE_RATE
        # 240 kHz stage: pass +-100 kHz (all of a broadcast FM channel).
        self.to_wide = FirDecimator(lowpass(self.input_rate, 105000, 30000), down1)
        low, high = s["filter_low"], s["filter_high"]
        width = max(high - low, 50)
        transition = max(width * FILTER_SHAPES.get(s["filter_shape"], 0.2), 50)
        if mode in WFM_MODES:
            half = max(abs(low), abs(high))
            self.channel = FirDecimator(lowpass(WIDE_RATE, min(half, 115000), max(transition, 8000)), 1)
            self.fm = QuadDemod()
            # Mono and L-R share one 15 kHz FIR by riding as real/imag parts.
            self.audio_lp = FirDecimator(lowpass(WIDE_RATE, 15000, 3000), WIDE_RATE // AUDIO_RATE)
            self.pilot = PhaseTracker(WIDE_RATE, 19000, 960)  # 4 ms windows
            # Empty guard band beside the pilot: noise there says how much of
            # the "pilot" a noisy channel would show without one.
            self.pilot_ref = PhaseTracker(WIDE_RATE, 17500, 960)
            self.deemph = [deemphasis(AUDIO_RATE, s["wfm_tau_us"]) for _ in range(2)]
        else:
            self.to_narrow = FirDecimator(lowpass(WIDE_RATE, 21000, 6000), WIDE_RATE // AUDIO_RATE)
            self.cw_shift = Nco(AUDIO_RATE)
            # Complex band-pass for an asymmetric passband: a low-pass of half
            # the width, shifted to the passband's centre.
            centre = (low + high) / 2.0
            proto = lowpass(AUDIO_RATE, min(width / 2.0, AUDIO_RATE / 2 - 100), transition)
            n = np.arange(len(proto)) - (len(proto) - 1) / 2
            taps = (proto * np.exp(2j * np.pi * centre * n / AUDIO_RATE)).astype(np.complex64)
            self.channel = FirDecimator(taps, 1)
            self.fm = QuadDemod()
            self.deemph = [deemphasis(AUDIO_RATE, s["nfm_tau_us"])]
            self.dc = Iir(np.array([1.0, -1.0]), np.array([1.0, -0.999]))
            self.carrier = PhaseTracker(AUDIO_RATE, 0.0, 240)
            self.agc = Agc()
        self.nb2_avg = 0.0
        self.squelch_gate = 0.0
        self.dirty = False

    def process(self, iq):
        """iq: complex64 at input_rate. Returns float32 (n, 2) at 48 kHz."""
        with self.lock:
            if self.dirty:
                self._build()
            s = dict(self.s)
        mode = s["mode"]
        self.last_mpx = None
        if s["nb1"]:
            mag = np.abs(iq)
            iq = np.where(mag > s["nb1_threshold"] * (mag.mean() + 1e-9), 0, iq).astype(np.complex64)
        x = self.nco(iq, s["offset"])
        wide = self.to_wide(x)
        if mode in WFM_MODES:
            ch = self.channel(wide)
            self._level(ch)
            audio = self._wfm(ch, stereo=(mode == "WFM (stereo)"))
            audio *= 10 ** (s["volume_db"] / 20.0)
        else:
            narrow = self.to_narrow(wide)
            if s["nb2"]:
                narrow = self._nb2(narrow, s["nb2_threshold"])
            if mode in ("CW-L", "CW-U"):
                shift = s["cw_offset"] if mode == "CW-U" else -s["cw_offset"]
                # Put the carrier at +-offset Hz; the channel filter is centred there.
                narrow = self.cw_shift(narrow, -shift)
            ch = self.channel(narrow)
            self._level(ch)
            mono = self._narrow(ch, mode, s)
            mono *= 10 ** (s["volume_db"] / 20.0)
            audio = np.stack((mono, mono), axis=1)
        audio = self._squelch(audio, s["squelch_db"])
        if s["mute"]:
            audio[:] = 0
        return np.clip(audio, -1.0, 1.0).astype(np.float32)

    def _level(self, ch):
        power = float(np.mean(np.abs(ch) ** 2)) if len(ch) else 0.0
        self.level_db = 10 * math.log10(power + 1e-15)

    def _nb2(self, x, threshold):
        mag = np.abs(x)
        avg = 0.9 * self.nb2_avg + 0.1 * float(mag.mean()) if self.nb2_avg else float(mag.mean())
        self.nb2_avg = avg
        hits = mag > threshold * avg
        if hits.any():
            x = x.copy()
            x[hits] = x[hits] / mag[hits] * avg
        return x

    def _squelch(self, audio, threshold):
        open_ = self.level_db >= threshold
        self.squelched = not open_
        target = 1.0 if open_ else 0.0
        if target == self.squelch_gate and target == 1.0:
            return audio
        ramp = np.linspace(self.squelch_gate, target, len(audio), dtype=np.float32)
        self.squelch_gate = target
        return audio * ramp[:, None]

    def _wfm(self, ch, stereo):
        mpx = self.fm(ch) * (WIDE_RATE / (2 * math.pi * 75000))  # 1.0 = 75 kHz deviation
        self.last_mpx = mpx  # Before de-emphasis, audio filtering, mute, or squelch.
        if stereo:
            phase, level = self.pilot(mpx)
            _, noise = self.pilot_ref(mpx)
            self.stereo = 2 * level >= STEREO_PILOT_MIN and level > 4 * noise
        else:
            self.stereo = False
        if self.stereo:
            carrier = np.cos(2 * phase).astype(np.float32)  # 38 kHz, locked to the pilot
            both = (mpx + 1j * (2 * mpx * carrier)).astype(np.complex64)
        else:
            both = mpx.astype(np.complex64)
        out = self.audio_lp(both)
        mono, diff = out.real.astype(np.float32), out.imag.astype(np.float32)
        left, right = (mono + diff) / 2, (mono - diff) / 2
        if not self.stereo:
            left = right = mono
        chans = []
        for i, chan in enumerate((left, right)):
            d = self.deemph[i]
            chans.append(d(chan) if d else chan)
        return np.stack(chans, axis=1) * 0.9

    def _narrow(self, ch, mode, s):
        if mode == "Narrow FM":
            audio = self.fm(ch) * (AUDIO_RATE / (2 * math.pi * max(s["fm_max_dev"], 500)))
            if self.deemph[0]:
                # De-emphasis of a pre-emphasised voice channel loses the top
                # octave's level; make up the loss so voices stay as loud.
                audio = self.deemph[0](audio) * 3.0
            return audio.astype(np.float32) * 0.5
        if mode == "AM":
            audio = np.abs(ch).astype(np.float32)
            if s["am_dcr"]:
                audio = self.dc(audio)
        elif mode == "AM-Sync":
            phase, _ = self.carrier(ch)
            audio = (ch * np.exp(-1j * phase)).real.astype(np.float32)
            if s["am_dcr"]:
                audio = self.dc(audio)
        else:  # SSB and CW: the filtered passband's real part is the audio
            audio = ch.real.astype(np.float32)
        if s["agc"] == "Off":
            return audio * 10 ** (s["agc_manual_gain_db"] / 20.0)
        preset = AGC_PRESETS.get(s["agc"])
        decay, hang = preset if preset else (s["agc_decay_ms"], s["agc_hang"])
        return self.agc(audio, decay, hang, s["agc_threshold_db"], s["agc_slope_db"])


class Spectrum:
    """Averaged power spectrum of the raw input, for the waterfall."""

    def __init__(self, size=4096):
        self.size = size
        self.window = signal.get_window("hann", size).astype(np.float32)
        self.norm = 20 * math.log10(self.window.sum())

    def __call__(self, iq, segments=4):
        n = self.size
        count = min(segments, len(iq) // n)
        if count == 0:
            return None
        step = len(iq) // count
        acc = np.zeros(n, dtype=np.float64)
        for i in range(count):
            seg = iq[i * step:i * step + n] * self.window
            acc += np.abs(np.fft.fftshift(np.fft.fft(seg))) ** 2
        return (10 * np.log10(acc / count + 1e-20) - self.norm).astype(np.float32)


def u8_to_iq(raw):
    data = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
    data = (data - 127.4) / 128.0
    return data.view(np.complex64)
