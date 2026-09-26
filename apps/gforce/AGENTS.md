# G-Force

`main.py` is the live Qt frontend; `renderer.cpp` renders the classic engine's
geometry with GLES3. `home/prog/gforce.nix` supplies the toolchain and pinned
upstream archive. `build.py` verifies that archive, applies `engine.patch`, and
builds into `~/.cache/gforce-build/<content-hash>/`. A successful cache entry is
immutable, so updates do not replace a running process's shared library.
Python edits take effect at next launch; native edits trigger a cached rebuild
on next launch. `nix-pull apply` is the normal update path on top and book/air.

The engine and its preset collection are fetched from Libvisual's pinned
upstream archive, not vendored. Preserve upstream attribution and license
notices; see README.md. Generate engine.patch against that revision. Only our
frontend, renderer, bridge, tests, and patch belong here; no upstream archives,
compiled libraries, screenshots, personal tuning, or presets in this tree.

Book uses native Fedora Python/Qt, gcc-c++, mesa-libGLES-devel,
mesa-libEGL-devel, fftw-libs-single and pulseaudio-utils. Top uses Nix packages
and player's Qt environment. `gforce-qtenv CMD...` supplies the appropriate
build/runtime environment without launching anything. `gforce --build-only`
prepares the renderer and prints its path without opening Qt or audio.

Dials and saved looks remain in ~/.config/gforce-vis. Shared dial tuning lives
in the optional private docs profile owned by shared_dials.py; application
updates and first builds do not require docs. Panel visibility is host-local.
launch.py migrates legacy engine preferences once, without deleting the old
install. GF_ENGINE_STATE_DIR selects the live engine preference directory;
without it, isolated libraries use their own build cache's state directory.

## Verification

Never launch the application on the live desktop for a test. The root and
apps guides' isolation rules apply. Build and test in an isolated cache:

```bash
export GF_BUILD_CACHE=$(mktemp -d /tmp/gforce-check.XXXXXX)
export GF_RENDERER_PATH=$(gforce --build-only)
unset DISPLAY WAYLAND_DISPLAY GF_ENGINE_STATE_DIR QT_QPA_PLATFORMTHEME
export QT_QPA_PLATFORM=offscreen
source tools/lib/session-guard.sh
sg_require_offscreen
gforce-qtenv python3 apps/gforce/connections-check.py
gforce-qtenv python3 apps/gforce/motion-check.py
gforce-qtenv python3 apps/gforce/field-cache-check.py
gforce-qtenv python3 apps/gforce/seam-check.py
```

The renderer harnesses use surfaceless EGL and synthetic audio. They write
engine preferences only inside that isolated build. fps-ui-check.py substitutes
a QWidget and stand-in renderer; it isolates local and shared settings. The
pure Python audio-window-check.py and shared-dials-check.py open no devices.
The remaining *-check.py harnesses cover presets, scales, trails and response.
Never point their GF_ENGINE_STATE_DIR at the user's configuration. Keep fixture
outputs under GF_BUILD_CACHE, not this source directory.

## Player embedding

`settings.py` and `native.py` share dial defaults and the renderer ABI with
Player's disposable `embedded_worker.py`. `player_audio.py` taps only the
identified Player stream; the standalone frontend's desktop monitor is not
used by the embedded view. Player owns visibility, keyboard routing, layout
and the worker lifecycle (see `../player/AGENTS.md`). Both top and book require
PipeWire's `pw-dump`, `pw-record` and `pw-link` (`pipewire-utils` on Fedora).

`embedded-check.py` uses the isolated renderer library/cache above, synthetic
PCM, temporary settings and the actual framed process protocol.
`player-audio-check.py` creates its own private audio server and session bus,
disables every hardware monitor, and verifies unrelated audio exclusion,
stream replacement and tap teardown. It requires `pipewire`, `wireplumber`
and `dbus-daemon`; it never changes the live graph.
