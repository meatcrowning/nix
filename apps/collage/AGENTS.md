# Browser collage exporter

Portable userscript for both top and book and other users' browsers. No local
service or runtime CDN imports. `collage.user.js` is the installable artifact;
edit `src/`, then `npm ci && npm run build` in this directory. The pinned
Mediabunny code and its license are bundled, not fetched by the installed script.

Export video by timestamps with WebCodecs and bounded decoder/encoder queues;
never substitute MediaRecorder or wall-clock playback. Reject unsupported
codecs/HDR explicitly. Preserve selected order, source timing, colour metadata,
and size-limit checks. Do not touch the live Vivaldi profile for installation.

Run `npm test` through `test.sh`: isolated headless Chromium, private profile,
no live D-Bus/display, and FFmpeg probes of generated synthetic fixtures.
No screenshots or real media are needed. Tests must not navigate to 4chan or
contact external hosts. `COLLAGE_BROWSER` may specify a browser executable.

Install `collage.user.js` in a userscript manager, disable older collage copies,
then reload the thread. Selection is per-thread; the first run reads the old
`highlightedImages_<thread>` list without modifying it. No browser profile writes
or automatic installation. A public raw file URL can be used for installation.

Limits: WebM (VP8, then VP9 if supported), silent SDR video, 1–15 seconds,
15/24/30/60 fps; 64 inputs, 8 video decoders, 24 MP total video dimensions,
32 MP resized stills, 256 MiB compressed inputs per collage. HDR video is refused.
Animated images become stills. Header is a full-width first row; multiple
collages distribute items round-robin. Output limits use decimal MB. PNG refuses
oversize; JPEG searches quality; video retries bitrate up to three passes.

Performance checks use deliberate >frame-period delays and frame-changing
synthetic video. Verify decoded output cadence and colour patches, not just the
encoder's frame counter. Do not claim older-browser or exact-colour compatibility
from API presence alone; the tested browser and tolerances belong in test reports.
