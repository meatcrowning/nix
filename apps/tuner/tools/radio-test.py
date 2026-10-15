#!/usr/bin/env python3
"""Run the real radio thread against the dongle for a few seconds, silently.

Playback is replaced by a WAV writer, so this reads the dongle (close gqrx
and tuner first) but never touches the audio device. It then judges the
decoded audio the same way dsp-test.py judges a recording.

    tools/radio-test.py 96900000 "WFM (stereo)" --seconds 6 --wav /tmp/fm.wav
"""

import argparse
import sys
import threading
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import dsp  # noqa: E402
import radio  # noqa: E402

dsp_test = __import__("dsp-test")


class Capture:
    def __init__(self):
        self.frames = []
        self.target = None

    def write(self, frames):
        self.frames.append(frames.copy())

    def set_target(self, target):
        pass

    def close(self):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("frequency", type=int)
    parser.add_argument("mode")
    parser.add_argument("--seconds", type=float, default=6)
    parser.add_argument("--gain", type=float, default=None, help="RF gain dB; default automatic")
    parser.add_argument("--wav")
    args = parser.parse_args()

    lo, hi = dsp.filter_for(dsp.canonical_mode(args.mode), "Normal")
    rx = {"mode": args.mode, "filter_low": lo, "filter_high": hi, "volume_db": 0}
    errors, stopped, levels = [], threading.Event(), []
    r = radio.Radio(rx, lambda *a: None,
                    lambda level, stereo, sq, overload, rec: levels.append((level, stereo, overload)),
                    errors.append, stopped.set)
    r.playback = Capture()
    r.start({"frequency": args.frequency, "sample_rate": 1920000, "gain_db": args.gain,
             "rtl_agc": False, "ppm": 0, "bias_tee": False, "device": 0})
    # Opening and tuning the dongle takes a couple of seconds; time from the first audio.
    deadline = time.monotonic() + 15
    while not r.playback.frames and not stopped.is_set() and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(args.seconds)
    r.stop()
    stopped.wait(5)
    if errors:
        print("FAIL radio: " + "; ".join(errors))
        return 1
    audio = np.concatenate(r.playback.frames) if r.playback.frames else np.zeros((0, 2), np.float32)
    level, stereo, overload = levels[-1] if levels else (-150, False, False)
    print("got %.1f s of audio; tuner %s; channel %.1f dBFS; stereo %s; overload %s"
          % (len(audio) / dsp.AUDIO_RATE, r.tuner, level, stereo, overload))
    stats = dsp_test.programme_report(audio, "%d" % args.frequency)
    ok = (len(audio) > dsp.AUDIO_RATE * (args.seconds - 1.5) and stats["rms"] > 0.01
          and stats["distinct"] > 8 and stats["flatness"] < 0.5)
    if args.wav:
        dsp_test.write_wav(args.wav, audio)
        print("wrote " + args.wav)
    print(("PASS" if ok else "FAIL") + " programme audio")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
