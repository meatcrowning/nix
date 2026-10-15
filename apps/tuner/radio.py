"""The radio thread: dongle -> receiver DSP -> playback / UDP / recorder.

Hardware changes are queued and applied between reads, so the GUI never
touches the dongle directly. Results come back through the callbacks, which
are called on the radio thread; the GUI marshals them with GLib.idle_add.
"""

import os
import queue
import threading
import time

import numpy as np

import audio
import dsp
import rtl

# 384 * 512 bytes = 98304 samples, about 51 ms at 1.92 MS/s.
READ_BYTES = 384 * 512
SAMPLE_RATES = [960000, 1200000, 1440000, 1680000, 1920000, 2160000, 2400000]
DC_GUARD = 20000  # keep the tuned channel this far from the dongle's DC spike
QUEUE_BLOCKS = 40   # about two seconds between the dongle and the DSP
BACKLOG_BLOCKS = 8  # more than this waiting (0.4 s) means drift: drop one


def nearest_rate(rate):
    return min(SAMPLE_RATES, key=lambda r: (abs(r - rate), -r))


class Radio:
    def __init__(self, rx_settings, on_spectrum, on_status, on_error, on_stopped):
        self.rx_settings = rx_settings
        self.on_spectrum, self.on_status, self.on_error, self.on_stopped = (
            on_spectrum, on_status, on_error, on_stopped)
        self.jobs = queue.Queue()
        self.thread = None
        self.running = False
        self.rate = 1920000
        self.center = 0
        self.freq = 0
        self.rx = None
        self.gains = []
        self.tuner = ""
        self.playback = audio.Playback()
        if os.environ.get("TUNER_TEST_SINK"):  # harnesses: write audio to a file, never play it
            self.playback = audio.FileSink(os.environ["TUNER_TEST_SINK"])
        self.samples_read = 0
        self.dropped = 0
        self.started = None
        self.udp = audio.UdpStream()
        self.udp_cfg = None  # (host, port, stereo) when streaming
        self.recorder = None
        self.overload = False
        self.on_recorded = lambda path, seconds: None

    # GUI-side API -------------------------------------------------------

    def start(self, hw):
        """hw: device, frequency, sample_rate, gain_db (None = auto), rtl_agc, ppm, bias_tee."""
        if self.running:
            return
        self.running = True
        self.rate = nearest_rate(hw["sample_rate"])
        self.rx = dsp.Receiver(self.rate, self.rx_settings)
        self.thread = threading.Thread(target=self._run, args=(dict(hw),), name="radio", daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def tune(self, freq):
        self.jobs.put(("tune", int(freq)))

    def hardware(self, key, value):
        self.jobs.put((key, value))

    def receiver(self, **changes):
        self.rx_settings.update(changes)
        if self.rx:
            self.rx.set(**changes)

    def set_output(self, target):
        self.jobs.put(("output", target))

    def set_udp(self, cfg):
        self.udp_cfg = cfg

    def start_recording(self, directory, mode):
        self.jobs.put(("record", (directory, mode)))

    def stop_recording(self):
        self.jobs.put(("record", None))

    # Radio thread -------------------------------------------------------

    def _run(self, hw):
        dongle = None
        try:
            dongle = rtl.Dongle(hw.get("device", 0))
            self.tuner = dongle.tuner
            self.gains = dongle.gains()
            dongle.set_sample_rate(self.rate)
            dongle.set_ppm(hw.get("ppm", 0))
            dongle.set_rtl_agc(hw.get("rtl_agc", False))
            dongle.set_gain(hw.get("gain_db"))
            dongle.set_bias_tee(hw.get("bias_tee", False))
            self.freq = int(hw["frequency"])
            self._recentre(dongle, self.freq)
            dongle.reset_buffer()
            blocks = queue.Queue(maxsize=QUEUE_BLOCKS)
            reader_error = []

            def on_data(raw):
                try:
                    blocks.put_nowait(raw)
                except queue.Full:
                    self.dropped += 1  # processing fell a second behind; skip

            def read():
                try:
                    dongle.read_async(on_data, 15, READ_BYTES)
                except OSError as exc:
                    reader_error.append(str(exc))
                blocks.put(None)

            reader = threading.Thread(target=read, name="dongle", daemon=True)
            reader.start()
            spectrum = dsp.Spectrum(4096)
            last_status = 0.0
            while self.running:
                self._drain(dongle)
                try:
                    raw = blocks.get(timeout=1)
                except queue.Empty:
                    continue
                if raw is None:
                    if reader_error:
                        raise OSError(reader_error[0])
                    break
                if self.started is None:
                    self.started = time.monotonic()
                self.samples_read += len(raw) // 2
                # The dongle's clock runs a little fast or slow against the
                # sound card's; when a backlog builds, drop a block rather
                # than let the delay grow without bound.
                if blocks.qsize() > BACKLOG_BLOCKS:
                    self.dropped += 1
                    continue
                u8 = np.frombuffer(raw, dtype=np.uint8)
                self.overload = float(np.count_nonzero((u8 == 0) | (u8 == 255))) / len(u8) > 0.005
                iq = dsp.u8_to_iq(raw)
                row = spectrum(iq, segments=2)
                if row is not None:
                    self.on_spectrum(row, self.center, self.rate)
                frames = self.rx.process(iq)
                self.playback.write(frames)
                cfg = self.udp_cfg
                if cfg:
                    self.udp.send(frames, *cfg)
                if self.recorder:
                    self.recorder.write(frames)
                now = time.monotonic()
                if now - last_status > 0.1:
                    last_status = now
                    self.on_status(self.rx.level_db, self.rx.stereo, self.rx.squelched, self.overload,
                                   self.recorder.frames / audio.RATE if self.recorder else None)
            dongle.cancel_async()
            reader.join(timeout=3)
        except OSError as exc:
            self.on_error(str(exc))
        finally:
            self.running = False
            self.playback.close()
            if self.recorder:
                self.on_recorded(*self.recorder.close())
                self.recorder = None
            if dongle:
                dongle.close()
            self.on_stopped()

    def _recentre(self, dongle, freq):
        # Park the dongle a quarter of the band below the channel: clear of
        # the DC spike, with room either side to tune without retuning.
        self.center = int(freq - self.rate // 4)
        dongle.set_center(self.center)
        self.rx.set(offset=float(freq - self.center))

    def _drain(self, dongle):
        while True:
            try:
                key, value = self.jobs.get_nowait()
            except queue.Empty:
                return
            if key == "tune":
                self.freq = value
                offset = value - self.center
                limit = self.rate / 2 - 135000
                if abs(offset) > limit or abs(offset) < DC_GUARD:
                    self._recentre(dongle, value)
                else:
                    self.rx.set(offset=float(offset))
            elif key == "gain_db":
                dongle.set_gain(value)
            elif key == "rtl_agc":
                dongle.set_rtl_agc(value)
            elif key == "ppm":
                dongle.set_ppm(value)
            elif key == "bias_tee":
                dongle.set_bias_tee(value)
            elif key == "sample_rate":
                self.rate = nearest_rate(value)
                dongle.set_sample_rate(self.rate)
                self.rx = dsp.Receiver(self.rate, self.rx_settings)
                self._recentre(dongle, self.freq)
                dongle.reset_buffer()
            elif key == "output":
                self.playback.set_target(value)
            elif key == "record":
                if self.recorder:
                    path, seconds = self.recorder.close()
                    self.recorder = None
                    self.on_recorded(path, seconds)
                if value:
                    directory, mode = value
                    self.recorder = audio.Recorder(directory, self.freq, mode)
