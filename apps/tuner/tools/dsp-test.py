#!/usr/bin/env python3
"""Offline checks for tuner's DSP: no dongle, no audio device.

Synthetic signals prove each demodulator recovers the right audio (and that
WFM stereo puts L and R in the right channels); --iq FILE:OFFSET:MODE decodes
a recording made with rtl_sdr -s 1920000 and reports whether the result looks
like programme audio rather than a tone or silence. --wav DIR writes what was
decoded so a human can listen to it.

    tools/dsp-test.py
    tools/dsp-test.py --iq fm.u8:-300000:"WFM (stereo)" --wav /tmp/out
"""

import argparse
import math
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dsp  # noqa: E402

FS = 1920000
FAILURES = []


def check(name, ok, detail):
    print(("PASS " if ok else "FAIL ") + name + ": " + detail)
    if not ok:
        FAILURES.append(name)


def run(rx, iq, block=262144):
    out = [rx.process(iq[i:i + block]) for i in range(0, len(iq), block)]
    return np.concatenate(out)


def tone_db(x, freq, rate=dsp.AUDIO_RATE):
    """Level of `freq` relative to the strongest bin, skipping the first 0.5 s."""
    x = x[rate // 2:]
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    bins = np.fft.rfftfreq(len(x), 1 / rate)
    k = np.argmin(np.abs(bins - freq))
    return 20 * math.log10(spec[max(k - 3, 0):k + 4].max() / spec.max() + 1e-12), spec, bins


def peak_freq(x, rate=dsp.AUDIO_RATE):
    _, spec, bins = tone_db(x, 0, rate)
    spec[bins < 50] = 0
    return bins[int(np.argmax(spec))]


def synth_fm(mpx, deviation, offset, rate=FS):
    phase = 2 * np.pi * np.cumsum(mpx * deviation / rate)
    t = np.arange(len(mpx)) / rate
    return np.exp(1j * (phase + 2 * np.pi * offset * t)).astype(np.complex64)


def synthetic():
    secs = 2.0
    t = np.arange(int(FS * secs)) / FS
    offset = 250000.0

    # WFM stereo: 1 kHz only on the left, 3 kHz only on the right.
    left, right = np.sin(2 * np.pi * 1000 * t), np.sin(2 * np.pi * 3000 * t)
    pilot = 2 * np.pi * 19000 * t
    mpx = 0.45 * (left + right) / 2 + 0.45 * (left - right) / 2 * np.cos(2 * pilot) + 0.1 * np.cos(pilot)
    iq = synth_fm(mpx, 75000, offset)
    rx = dsp.Receiver(FS, {"mode": "WFM (stereo)", "offset": offset, "wfm_tau_us": 0, "volume_db": 0})
    out = run(rx, iq)
    l_own, _, _ = tone_db(out[:, 0], 1000)
    l_leak, _, _ = tone_db(out[:, 0], 3000)
    r_own, _, _ = tone_db(out[:, 1], 3000)
    r_leak, _, _ = tone_db(out[:, 1], 1000)
    check("wfm stereo pilot", rx.stereo, "stereo=%s" % rx.stereo)
    check("wfm stereo separation", l_own > -1 and r_own > -1 and l_leak < -20 and r_leak < -20,
          "L: 1k %.1f dB, 3k %.1f dB; R: 3k %.1f dB, 1k %.1f dB" % (l_own, l_leak, r_own, r_leak))

    rx = dsp.Receiver(FS, {"mode": "WFM (mono)", "offset": offset, "wfm_tau_us": 0})
    out = run(rx, iq)
    check("wfm mono", np.allclose(out[:, 0], out[:, 1]) and peak_freq(out[:, 0]) in (1000, 3000),
          "peak %.0f Hz" % peak_freq(out[:, 0]))

    # Narrow FM, 1 kHz at 3 kHz deviation.
    iq = synth_fm(np.sin(2 * np.pi * 1000 * t), 3000, -offset)
    rx = dsp.Receiver(FS, {"mode": "Narrow FM", "offset": -offset, "filter_low": -5000,
                           "filter_high": 5000, "nfm_tau_us": 0})
    out = run(rx, iq)
    check("nfm", abs(peak_freq(out[:, 0]) - 1000) < 5, "peak %.0f Hz" % peak_freq(out[:, 0]))

    # AM, 1.2 kHz at 50 %.
    carrier = np.exp(2j * np.pi * -offset * t)
    iq = ((1 + 0.5 * np.sin(2 * np.pi * 1200 * t)) * carrier * 0.3).astype(np.complex64)
    for mode in ("AM", "AM-Sync"):
        rx = dsp.Receiver(FS, {"mode": mode, "offset": -offset, "filter_low": -5000, "filter_high": 5000})
        out = run(rx, iq)
        rms = float(np.sqrt(np.mean(out[FS // 40:, 0] ** 2)))
        check(mode.lower(), abs(peak_freq(out[:, 0]) - 1200) < 5 and rms > 0.02,
              "peak %.0f Hz, rms %.3f" % (peak_freq(out[:, 0]), rms))

    # USB: a tone 1.5 kHz above the dial; LSB: 1.5 kHz below.
    for mode, sign in (("USB", 1), ("LSB", -1)):
        iq = (0.2 * np.exp(2j * np.pi * (-offset + sign * 1500) * t)).astype(np.complex64)
        lo, hi = dsp.filter_for(mode, "Normal")
        rx = dsp.Receiver(FS, {"mode": mode, "offset": -offset, "filter_low": lo, "filter_high": hi})
        out = run(rx, iq)
        check(mode.lower(), abs(peak_freq(out[:, 0]) - 1500) < 5, "peak %.0f Hz" % peak_freq(out[:, 0]))
        # The opposite sideband must be rejected.
        iq = (0.2 * np.exp(2j * np.pi * (-offset - sign * 1500) * t)).astype(np.complex64)
        rx = dsp.Receiver(FS, {"mode": mode, "offset": -offset, "filter_low": lo, "filter_high": hi,
                               "agc": "Off"})
        rejected = float(np.sqrt(np.mean(run(rx, iq)[FS // 40:, 0] ** 2)))
        check(mode.lower() + " rejects other sideband", rejected < 0.01, "rms %.4f" % rejected)

    # CW: a carrier exactly on the dial comes out at the CW offset.
    iq = (0.2 * np.exp(2j * np.pi * -offset * t)).astype(np.complex64)
    for mode in ("CW-U", "CW-L"):
        rx = dsp.Receiver(FS, {"mode": mode, "offset": -offset, "filter_low": -250, "filter_high": 250,
                               "cw_offset": 700})
        out = run(rx, iq)
        check(mode.lower(), abs(peak_freq(out[:, 0]) - 700) < 5, "peak %.0f Hz" % peak_freq(out[:, 0]))

    # Squelch closes on noise.
    noise = (np.random.default_rng(1).normal(size=2 * len(t)) * 0.001).astype(np.float32).view(np.complex64)
    rx = dsp.Receiver(FS, {"mode": "Narrow FM", "offset": -offset, "squelch_db": -40})
    out = run(rx, noise)
    check("squelch", float(np.abs(out[dsp.AUDIO_RATE // 2:]).max()) == 0.0 and rx.squelched,
          "level %.1f dBFS" % rx.level_db)


def programme_report(audio, name):
    """Programme audio varies: its spectrum changes frame to frame and is broad."""
    mono = audio.mean(axis=1)
    frame = dsp.AUDIO_RATE // 10
    frames = mono[: len(mono) // frame * frame].reshape(-1, frame)[5:]
    rms = np.sqrt((frames ** 2).mean(axis=1))
    spec = np.abs(np.fft.rfft(frames * np.hanning(frame), axis=1)) + 1e-9
    flatness = np.exp(np.log(spec).mean(axis=1)) / spec.mean(axis=1)
    peaks = np.fft.rfftfreq(frame, 1 / dsp.AUDIO_RATE)[spec.argmax(axis=1)]
    # A steady tone keeps one peak and a flat level; noise is spectrally flat.
    distinct = len(set(np.round(peaks / 50)))
    level_spread = float(np.std(20 * np.log10(rms + 1e-9)))
    # Energy in the voice band vs the whole spectrum.
    total = spec.sum(axis=1)
    bins = np.fft.rfftfreq(frame, 1 / dsp.AUDIO_RATE)
    voice = spec[:, (bins > 200) & (bins < 4000)].sum(axis=1) / total
    print("  %s: rms %.3f, level spread %.1f dB, %d distinct peak bins, flatness %.2f, "
          "voice-band share %.2f" % (name, float(rms.mean()), level_spread, distinct,
                                      float(flatness.mean()), float(voice.mean())))
    return dict(rms=float(rms.mean()), spread=level_spread, distinct=distinct,
                flatness=float(flatness.mean()))


def write_wav(path, audio):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(dsp.AUDIO_RATE)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())


def recording(spec, wav_dir):
    path, offset, mode = spec.split(":", 2)
    raw = Path(path).read_bytes()
    iq = dsp.u8_to_iq(raw)
    seconds = len(iq) / FS
    lo, hi = dsp.filter_for(mode, "Normal")
    rx = dsp.Receiver(FS, {"mode": mode, "offset": float(offset), "filter_low": lo, "filter_high": hi})
    start = time.process_time()
    audio = run(rx, iq)
    cpu = time.process_time() - start
    name = Path(path).stem
    print("%s (%s, %.1f s): channel %.1f dBFS, stereo %s, decode used %.0f%% of real time"
          % (name, mode, seconds, rx.level_db, rx.stereo, 100 * cpu / seconds))
    stats = programme_report(audio, name)
    check(name + " decodes in real time", cpu < seconds * 0.6, "%.2f s CPU for %.1f s" % (cpu, seconds))
    check(name + " is programme audio", stats["rms"] > 0.01 and stats["distinct"] > 8
          and stats["flatness"] < 0.5, "see report above")
    if mode == "WFM (stereo)":
        side = audio[:, 0] - audio[:, 1]
        ratio = float(np.sqrt((side ** 2).mean()) / (np.sqrt((audio ** 2).mean()) + 1e-9))
        check(name + " has distinct channels", rx.stereo and ratio > 0.02, "L-R/total %.3f" % ratio)
    if wav_dir:
        Path(wav_dir).mkdir(parents=True, exist_ok=True)
        out = Path(wav_dir) / (name + ".wav")
        write_wav(out, audio)
        print("  wrote " + str(out))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iq", action="append", default=[])
    parser.add_argument("--wav")
    parser.add_argument("--no-synthetic", action="store_true")
    args = parser.parse_args()
    if not args.no_synthetic:
        synthetic()
    for spec in args.iq:
        recording(spec, args.wav)
    print("FAILED: " + ", ".join(FAILURES) if FAILURES else "all passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
