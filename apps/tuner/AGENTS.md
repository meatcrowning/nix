# apps/tuner — RTL-SDR receiver (top only)

A GTK 3 / PyGObject app, unlike the Qt apps beside it: it is made for top's
Unity 12.10 session, which themes host GTK apps with Ambiance Dark and the
Ubuntu font, so it uses stock GTK widgets and draws the dial and
spectrum/waterfall (views.py), plus the segmented RDS face (rdsview.py).
The dongle and package are top-only
(sys/hw/rtl-sdr.nix, home/prog/tuner.nix); there is no air branch.

| file | owns |
|---|---|
| dsp.py | demodulators, filters, AGC, squelch, noise blankers; numpy/scipy only |
| rds.py | bounded asynchronous Redsea MPX pipe and station metadata; no device access |
| online.py | bounded background station-feed requests; local bookmark associations |
| rdsview.py | scrolling fourteen-segment RDS display and its map/unmap timer |
| hd.py | nrsc5 pipe API, HD metadata and streaming 44.1→48 kHz conversion; no device access |
| hdreceiver.py | HD capture session and bounded burst-audio output worker |
| radio.py | the radio thread: librtlsdr reads, retuning, playback/UDP/recorder |
| rtl.py | ctypes librtlsdr binding (`TUNER_LIBRTLSDR` from the wrapper) |
| audio.py | `pw-cat` playback, PipeWire sink list, gqrx-format UDP, WAV recorder |
| gqrxfiles.py | gqrx's bookmarks.csv (read and written, shared) and default.conf (read once) |

Settings live in ~/.config/tuner/settings.json; the first run seeds them from
gqrx's default.conf. Bookmarks are gqrx's file, written atomically in gqrx's
column format; keep the two programs able to share it.

The dongle hands out only one reader: gqrx and tuner cannot run together.

RDS uses the pre-audio 240 kHz FM multiplex in both WFM modes, independently
of mute/squelch. The wrapper supplies `TUNER_REDSEA`; the subprocess never opens
the dongle. Retuning, mode changes, and receive sessions invalidate decoder
results by generation. Do not persist received station text. Confirmed named
FM bookmarks may supply fallback identity, explicitly labeled Bookmark rather
than received RDS.
The top controls and readouts share a car-stereo face (faceplate.py): three
rows (transport and settings; signal and go-to; frequency with station text),
every character one size (faceplate.SIZE). Typeset labels use the local
fourteen-segment font; drawn readouts and bargraph meters use faceplate.cell(),
which matches the font's outlines. Lit segments take the GTK theme's selection
colour and glow (faceplate.glow). The dial reads in MHz with only significant
digits shown; one blank hover cell after them keeps finer digits tunable.
Regenerate segment.ttf with tools/build-segment-font.py (fontTools)
when changing the rdsview.py geometry. Fontconfig registers it in-process only.
The frequency and station text remain visible together, regardless of old Text
preferences; the station line omits the frequency the dial already shows.
HD selection is in the Radio menu. Unavailable, waiting, and lost-signal
states are explicit. The marquee advances whole characters through
fixed segment cells; GTK's animation setting governs it. Metadata resets must
never discard the audio IQ queue; RDS conversion stays in its worker.

HD uses `TUNER_NRSC5` (libnrsc5) in pipe mode; the existing RTL binding remains
the sole dongle owner. HD fixes capture at 1,488,375 samples/s, centered on the
station. The analog rate and receiver settings are retained but disabled in HD.
Mode switches wait for the old receive thread to release the dongle. Discovered
public subchannels populate the selector; retuning resets to HD1 and discards
old station metadata/audio. Audio is resampled with continuous history to the
existing 48 kHz playback/UDP/WAV contract. No automatic analog fallback or
received metadata persistence.

Online text uses `online.json` beside the selected settings file, keyed by the
exact confirmed FM bookmark name. Keep personal station associations local.
Each value has an HTTPS `url` and `kind`: `json` (default), `icy`, or `spinitron`.
JSON accepts dot-separated `artist` and `title` paths, defaulting to
`nowPlaying.artistName` and `nowPlaying.songTitle`. Spinitron uses its public
`now-playing-v2` widget with a numeric `_spinitron` callback and `num=1`; its
latest entry is labeled Last logged, not assumed to be playing now.
Only one worker runs, polling every 30 seconds while receiving analog WFM
without fresh RadioText. Failures clear song text; retunes, stop, and HD changes
invalidate replies. Online text is labeled separately and may differ from FM.
Missing feeds retain the confirmed bookmark name. Reload source mappings by
reopening Tuner; no credentials or new dependencies are required.

## Verification

- `python3 tools/online-test.py` checks mocked feeds, response limits, late replies,
  failures, polling, and the actual display method without GTK or device access.
- `tools/hd-test.py` checks the real nrsc5 pipe, metadata/channel separation,
  continuous resampling, and a paced fake-dongle session with a memory sink.
  Set `TUNER_NRSC5` to the wrapper library; optional `--sample PATH` accepts
  upstream nrsc5 `support/sample.xz` for real HD1/HD2 decoding.
- `bash tools/hd-ui-test.sh /path/to/tuner-python` runs HD controls, station
  reset, mode handoff, persistence and segment-colour checks on private Xvfb
  with scratch configuration, mocked device enumeration and no audio.

- `tools/rds-test.py` uses synthetic FM IQ through the real receiver and Redsea
  to verify PS/RadioText, 0A/0B/2A/2B groups, reset, and decoder teardown. Run
  with the wrapper's Python interpreter and `TUNER_REDSEA` executable path;
  read those paths from the wrapper, never source it. No GUI or hardware.
- `tools/dsp-test.py` checks every mode, WFM stereo separation and squelch on
  synthetic signals. `--iq FILE:OFFSET:MODE --wav DIR` decodes an `rtl_sdr -s
  1920000` capture and reports whether the result is programme audio rather
  than a tone or noise; use it after any DSP change. Capturing with `rtl_sdr`
  touches only the dongle, never the user's audio.
- `tools/shot.sh OUT.png TUNER_BIN --feed synthetic` renders the window on a
  private Xvfb with a scratch config and a copy of the bookmarks; set
  `TUNER_SHOT_TAB=0..4` for a notebook page. Never start the app on the real
  display, and never let a test play audio.
