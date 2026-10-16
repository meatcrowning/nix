# apps/tuner — RTL-SDR receiver (top only)

A GTK 3 / PyGObject app, unlike the Qt apps beside it: it is made for top's
Unity 12.10 session, which themes host GTK apps with Ambiance Dark and the
Ubuntu font, so it uses stock GTK widgets and draws only the dial and the
spectrum/waterfall (views.py). The dongle and package are top-only
(sys/hw/rtl-sdr.nix, home/prog/tuner.nix); there is no air branch.

| file | owns |
|---|---|
| dsp.py | demodulators, filters, AGC, squelch, noise blankers; numpy/scipy only |
| radio.py | the radio thread: librtlsdr reads, retuning, playback/UDP/recorder |
| rtl.py | ctypes librtlsdr binding (`TUNER_LIBRTLSDR` from the wrapper) |
| audio.py | `pw-cat` playback, PipeWire sink list, gqrx-format UDP, WAV recorder |
| gqrxfiles.py | gqrx's bookmarks.csv (read and written, shared) and default.conf (read once) |

Settings live in ~/.config/tuner/settings.json; the first run seeds them from
gqrx's default.conf. Bookmarks are gqrx's file, written atomically in gqrx's
column format; keep the two programs able to share it.

The dongle hands out only one reader: gqrx and tuner cannot run together.

## Verification

- `tools/dsp-test.py` checks every mode, WFM stereo separation and squelch on
  synthetic signals. `--iq FILE:OFFSET:MODE --wav DIR` decodes an `rtl_sdr -s
  1920000` capture and reports whether the result is programme audio rather
  than a tone or noise; use it after any DSP change. Capturing with `rtl_sdr`
  touches only the dongle, never the user's audio.
- `tools/shot.sh OUT.png TUNER_BIN --feed synthetic` renders the window on a
  private Xvfb with a scratch config and a copy of the bookmarks; set
  `TUNER_SHOT_TAB=0..4` for a notebook page. Never start the app on the real
  display, and never let a test play audio.
