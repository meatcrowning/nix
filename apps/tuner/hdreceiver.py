"""HD receive session; the existing RTL binding remains the sole device owner.

nrsc5 emits audio in bursts. A bounded output worker keeps playback backpressure
out of the IQ reader/decoder and preserves 48 kHz recording and UDP contracts.
"""
import queue
import threading
import time

import numpy as np

import audio
import dsp
import hd
import rtl


def run(radio, hw):
    dongle = decoder = reader = writer = None
    blocks = queue.Queue(maxsize=40)
    outputs = queue.Queue(maxsize=128)
    output_jobs = queue.Queue()
    errors = []
    done = threading.Event()
    serial = [0]
    generation = radio.metadata_generation
    last_status = 0.0
    gap = threading.Event()

    def metadata(data):
        radio.on_hd(generation, data)

    def decoded(frames):
        try:
            outputs.put_nowait((serial[0], frames))
        except queue.Full:
            raise OSError('HD audio output is too slow; select another output device')

    def output():
        resampler, previous = hd.Resampler(), -1
        try:
            while not done.is_set():
                while not output_jobs.empty():
                    key, value = output_jobs.get_nowait()
                    radio._output_job(key, value)
                try:
                    epoch, frames = outputs.get(timeout=.05)
                except queue.Empty:
                    continue
                if epoch != serial[0]:
                    continue
                if epoch != previous:
                    resampler, previous = hd.Resampler(), epoch
                frames = resampler.process(frames)
                if not len(frames):
                    continue
                frames *= 0 if radio.rx_settings['mute'] else 10 ** (radio.rx_settings['volume_db'] / 20)
                radio.playback.write(frames)
                if radio.udp_cfg:
                    radio.udp.send(frames, *radio.udp_cfg)
                if radio.recorder:
                    radio.recorder.write(frames)
        except Exception as exc:
            errors.append(str(exc))
            radio.running = False
        finally:
            radio.playback.close()
            radio._output_job('record', None)

    try:
        # Fail before acquiring the dongle if the packaged decoder is missing.
        decoder = hd.Decoder(metadata, decoded, radio.hd_program)
        dongle = rtl.Dongle(hw.get('device', 0))
        radio.tuner, radio.gains = dongle.tuner, dongle.gains()
        radio.rate = hd.RATE
        radio.freq = radio.center = int(hw['frequency'])
        dongle.set_sample_rate(hd.RATE)
        dongle.set_ppm(hw.get('ppm', 0))
        dongle.set_rtl_agc(hw.get('rtl_agc', False))
        dongle.set_gain(hw.get('gain_db'))
        dongle.set_bias_tee(hw.get('bias_tee', False))
        dongle.set_center(radio.freq)
        dongle.reset_buffer()
        spectrum = dsp.Spectrum(4096)

        def captured(raw):
            try:
                blocks.put_nowait((radio.metadata_generation, raw))
            except queue.Full:
                radio.dropped += 1
                gap.set()

        def read():
            try:
                dongle.read_async(captured, 15, 196608)
            except OSError as exc:
                errors.append(str(exc))
            finally:
                done.set()

        writer = threading.Thread(target=output, name='hd-audio', daemon=True)
        reader = threading.Thread(target=read, name='hd-dongle', daemon=True)
        writer.start()
        reader.start()
        metadata(decoder.state)
        while radio.running and not done.is_set():
            reset = False
            while not radio.jobs.empty():
                key, value = radio.jobs.get_nowait()
                if key == 'tune':
                    radio.freq = radio.center = value
                    dongle.set_center(value)
                    reset = True
                elif key == 'ppm':
                    dongle.set_ppm(value)
                    reset = True
                elif key == 'hd_program':
                    serial[0] += 1
                    decoder.select(value)
                elif key in ('output', 'record'):
                    output_jobs.put((key, value))
                elif key == 'gain_db':
                    dongle.set_gain(value)
                elif key == 'rtl_agc':
                    dongle.set_rtl_agc(value)
                elif key == 'bias_tee':
                    dongle.set_bias_tee(value)
                # Analog sample rate is saved by the UI, never applied to HD.
            if reset or gap.is_set():
                gap.clear()
                serial[0] += 1
                decoder.close()
                generation = radio.metadata_generation
                decoder = hd.Decoder(metadata, decoded, radio.hd_program)
                while not blocks.empty():
                    blocks.get_nowait()
                metadata(decoder.state)
            try:
                captured_generation, raw = blocks.get(timeout=.1)
            except queue.Empty:
                continue
            if captured_generation != generation or generation != radio.metadata_generation:
                continue
            iq = dsp.u8_to_iq(raw)
            radio.samples_read += len(iq)
            row = spectrum(iq, segments=2)
            if row is not None:
                radio.on_spectrum(row, radio.center, radio.rate)
            if time.monotonic() - radio.metadata_changed > .35:
                decoder.process(raw)
            now = time.monotonic()
            if now - last_status > .25:
                last_status = now
                decoder._publish()  # expire the audio-lock indicator on silence
                level = 10 * np.log10(max(float(np.mean(np.abs(iq) ** 2)), 1e-15))
                u8 = np.frombuffer(raw, np.uint8)
                overload = np.count_nonzero((u8 == 0) | (u8 == 255)) / len(u8) > .005
                radio.on_status(level, False, False, overload,
                                radio.recorder.frames / audio.RATE if radio.recorder else None)
        if errors:
            raise OSError(errors[0])
    except Exception as exc:
        radio.on_error(str(exc))
    finally:
        radio.running = False
        done.set()
        if dongle:
            dongle.cancel_async()
        if reader:
            reader.join()
        if writer:
            writer.join()
        if decoder:
            decoder.close()
        if dongle:
            dongle.close()
        radio.on_stopped()
