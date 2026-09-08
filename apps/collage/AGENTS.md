# Browser collage exporter

Portable userscript for both top and book and other users' browsers. No local
service. `collage.user.js` is the installable artifact;
edit `src/`, then `npm ci && npm run build` in this directory. The pinned
Mediabunny browser build is loaded by the manager through a version-pinned jsDelivr
`@require` with SHA-256 integrity computed from the installed npm package. Keep
the collage artifact unminified with readable names and comments; `src/mediabunny.js`
adapts the library's global namespace to named imports. Installation requires CDN
access; all media processing remains local. No Nix package or rebuild is involved.

Export video by timestamps with WebCodecs and bounded decoder/encoder queues;
never substitute MediaRecorder or wall-clock playback. Reject unsupported
codecs/HDR explicitly. Preserve selected order, source timing, colour metadata,
and size-limit checks. Do not touch the live Vivaldi profile for installation.

Run `npm test` through `test.sh`: isolated headless browser, private profile,
no live D-Bus/display, and FFmpeg probes of generated synthetic fixtures.
No screenshots or real media are needed. Tests must not navigate to 4chan or
contact external hosts. Load the exact npm browser build before the engine and
check the metadata hash. Test the installed artifact concatenated directly after
that build inside one function, as Tampermonkey injects it; separate script tags
miss automatic-semicolon-insertion failures. Keep the artifact's leading separator:
Mediabunny's final CommonJS conditional has no semicolon and can swallow our IIFE.
`COLLAGE_ENGINE=chromium|firefox|webkit` selects the
engine (default Chromium); `COLLAGE_BROWSER` may specify its executable.
Use matching Playwright/browser revisions for Firefox/WebKit. Set
`PLAYWRIGHT_BROWSERS_PATH` and optionally `COLLAGE_PLAYWRIGHT` to a matching
driver's absolute `index.mjs` when using system-provided test browsers.
`COLLAGE_CPU_RATE=6` exercises Chromium with 6× JavaScript CPU throttling;
this is not a low-memory device or hardware-codec emulator. Tests report an
image-only pass separately when a browser build lacks usable video encoders.

Install `collage.user.js` in a userscript manager, disable older collage copies,
then reload the thread. Selection is per-thread; the first run reads the old
`highlightedImages_<thread>` list without modifying it. No browser profile writes
or automatic installation. A public raw file URL can be used for installation.

Limits: WebM (VP8, then VP9 if supported) or explicit MP4 (AVC/H.264), silent SDR video, up to 300 seconds,
15/24/30/60 fps; 64 inputs,
32 MP resized stills, 256 MiB compressed inputs per collage. HDR video is refused.
Video jobs exceeding 8 videos or 24 × 1024² source pixels warn after metadata
loading, before export decoders start; these are warning thresholds, not limits.
Continue accepts the whole create operation; the next operation warns again.
The optional permanent dismissal uses userscript-manager storage across threads
and sites (origin localStorage fallback only without GM APIs). Escape/cancel aborts;
storage failures remain visible and never pretend the preference was saved.
Frame/timestamp validation remains mandatory regardless of warning dismissal.
Animated images become stills. Header is a full-width first row; multiple
collages distribute items round-robin. Output limits use decimal MB. PNG refuses
oversize; JPEG searches quality; video retries bitrate up to three passes.
The MB setting applies to each final collage, never individual inputs. Default
to 4,194,304 bytes (/g/'s 4 MiB), displayed as 4.194304 decimal MB. Check the
finished Blob size again immediately before download; refuse oversize output
without silently resizing, truncating or changing fps. Input memory guards remain
separate from this output budget.

Performance checks use deliberate >frame-period delays and frame-changing
synthetic video. Verify decoded output cadence and colour patches, not just the
encoder's frame counter. Do not claim older-browser or exact-colour compatibility
from API presence alone; the tested browser and tolerances belong in test reports.

Probe codecs with quality latency and no hardware preference. Do not infer
codec availability or reduce output settings from OS, CPU count or deviceMemory;
macOS and Asahi can expose different codecs on identical hardware. Retain WebM
as the posting default; never silently change containers. Unsupported video
encoding must leave image output usable. MP4 is not accepted by every destination.
Release still tiles after drawing the reusable base; yield through MessageChannel
without a per-frame timer clamp. Keep output timestamps independent of work time.
No MediaRecorder fallback, runtime codec downloads or platform-specific service.
Video export uses sequential VideoSampleSink.samples decoding, not sparse
samplesAtTimestamps: sparse GOP flushes can miss reordered H.264 frames. Each
reader owns its current frame and one lookahead, resamples by presentation time,
and restarts only at loop boundaries. Never close a borrowed frame in the draw
loop. Release both samples and the iterator on retry, cancellation and failure.
Keep synthetic B-frame/keyframe-boundary, VFR/offset/loop and ownership tests;
report the H.264 regression as skipped if the test browser lacks that decoder.
Source diagnostics include the file name and output-frame index. Invalid settings
are rejected before downloads; disabled video fields cannot block image exports.

The main panel exposes a positive decimal/colon/fraction aspect ratio and a
dark theme shared with the main collage button and controls; respect forced
colours for accessibility, and keep unselected thread buttons yellow; selected buttons and gallery tiles
share a light green background with black text. It has a
scale slider (1280px longest edge at 100%) above the gallery, with one create action. Advanced contains
format, fps, duration, size limit, collage count, local files and header input.
The default automatic format is resolved from decoded input types per collage:
any video selects WebM, otherwise JPEG. Explicit formats always override this.
Opening/creating discovers thread media without a separate import step; creation
uses the checked selection, never silently selects unchecked files. The collage
button toggles the panel; progress and X share a sticky top row. Thread selection
buttons use black text on yellow and sit inline after file dimensions without
increasing the text row height.
Place buttons after X/XT's formatted .file-info and before sauce links, without
rewriting or removing those links. Reconcile late file-info rebuilds via the
existing observer; avoid unconditional text mutations that create observer loops.
Finished files request native browser downloads automatically, with no result cards;
download permissions/save dialogs remain browser-controlled. Revoke download URLs
after 60 seconds, not immediately or on the next export. Never claim a confirmed
disk write from an anchor click. Every source tile has a preview button, independent
of its checkbox. Source previews use full media URLs, not thumbnails.
Gallery thumbnails reuse images/posters inside attachment or post links. Videos
without one decode a single paused frame into a display-only canvas when near
the visible gallery, with at most two decoders and a 12-second timeout. Release
each video source after capture/failure; never read back cross-origin canvases.
Thumbnail failures must leave the full preview button and export usable. Local
object URLs are retained until clear. A top-layer dialog covers the viewport;
clicking its background, an image, X or Escape returns to the gallery (video
controls remain interactive). Never test this by clicking the user's desktop.
All/selected is a display filter, not a selection change. List every thread file;
Clear imported removes local gallery entries and the local header, releasing
their object URLs; it preserves thread files, their selection and saved selection.
the 64-input export limit is separate from the gallery's size. No reorder buttons.
Blank seconds means longest input video, rounded up to the next output frame;
image-only video export defaults to five seconds. Explicit seconds overrides it.
Reject auto durations over 300s rather than silently truncating. Image layout fits
undistorted tiles inside the requested output ratio with padding as needed. Video
layout compares justified row arrangements against the requested ratio and uses
the actual content dimensions, without added borders or cropping;
dimensions are rounded to even pixels. Keep the distributed namespace anonymous.
