#!/usr/bin/env bash
# Render tuner on a private Xvfb display and save a PNG: no dongle, no audio,
# a scratch config, and a copy of gqrx's bookmarks so the real file is never
# written. Usage: tools/shot.sh OUT.png [TUNER_BIN] [--feed IQFILE]
set -euo pipefail
out=$1
bin=${2:-tuner}
scratch=$(mktemp -d "${TMPDIR:-/tmp}/tuner-shot.XXXXXX")
display=:$((90 + RANDOM % 50))
xvfb=$(nix build --no-link --print-out-paths nixpkgs#xvfb)/bin/Xvfb
magick=$(nix build --no-link --print-out-paths nixpkgs#imagemagick)/bin/import

mkdir -p "$scratch/cfg/gtk-3.0" "$scratch/rt" "$scratch/gqrx"
chmod 700 "$scratch/rt"
cp ~/.config/gqrx/bookmarks.csv ~/.config/gqrx/default.conf "$scratch/gqrx/" 2>/dev/null || true
printf '[Settings]\ngtk-theme-name=Ambiance-Dark\ngtk-icon-theme-name=ubuntu-mono-dark\ngtk-font-name=Ubuntu 11\n' \
  >"$scratch/cfg/gtk-3.0/settings.ini"

"$xvfb" "$display" -screen 0 1280x820x24 -nolisten tcp >/dev/null 2>&1 &
xpid=$!
cleanup() { kill "${apid:-}" 2>/dev/null || true; kill "$xpid" 2>/dev/null || true; wait 2>/dev/null || true; }
trap cleanup EXIT
sleep 1

# SHOT_START=1 lets it start receiving (with TUNER_TEST_SINK, audio goes to a file).
if [ -n "${SHOT_START:-}" ]; then start=(); else start=(--no-start); fi

# Positive isolation check: the target display must be our Xvfb, never :0.
[ "$display" != ":0" ] || exit 1
env -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u PULSE_SERVER -u PIPEWIRE_REMOTE \
  DISPLAY="$display" GDK_BACKEND=x11 HOME="$scratch" XDG_CONFIG_HOME="$scratch/cfg" \
  XDG_RUNTIME_DIR="$scratch/rt" TUNER_GQRX_DIR="$scratch/gqrx" TUNER_SHOT_FEED="${4:-}" TUNER_TEST_SINK="${TUNER_TEST_SINK:-}" \
  NO_AT_BRIDGE=1 dbus-run-session -- "$bin" "${start[@]}" >"$scratch/log" 2>&1 &
apid=$!
sleep "${SHOT_WAIT:-6}"
"$magick" -display "$display" -window root "$out"
echo "log:"; cat "$scratch/log"
