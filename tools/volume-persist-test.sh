#!/usr/bin/env bash
# Does THIS host remember its volume across a logout or a reboot?
#
# Volume persistence is not something this repo implements — WirePlumber does
# it, and the answer is per-host because the state lives in a machine-local
# file that does not sync:
#
#   ~/.local/state/wireplumber/stream-properties   node volumes (sinks/sources
#                                                  with no device route, and
#                                                  every application stream)
#   ~/.local/state/wireplumber/default-routes      route volumes (ALSA/bluez
#                                                  devices that have routes)
#
# The panel only ever writes through `wpctl set-volume <sink>` (SysInfo.qml)
# and reads back through scripts/sysinfo.sh, so if those two files are written
# and read the level survives; nothing in ~/nix stores a volume of its own.
#
# Two parts, and both are safe to run while he is listening:
#
#   LIVE   read-only. Prints the default sink/source volume, the saved value
#          for each, and whether the restore hooks are even enabled. A live
#          value that disagrees with the saved one is the symptom to chase.
#   ISOLATED  spins a private pipewire + wireplumber (own XDG_RUNTIME_DIR,
#          own state dir, own dbus, device monitors disabled so it cannot
#          contend for a real card), sets a volume on a null sink, restarts
#          both daemons and reads it back. This never touches the session
#          graph — no sink of his is opened, moved or re-levelled.
#
# Usage: tools/volume-persist-test.sh [--keep]     (--keep leaves $DIR around)
set -uo pipefail

DIR=${VOLTEST_DIR:-/tmp/volume-persist-test.$$}
KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1

STATE="${XDG_STATE_HOME:-$HOME/.local/state}/wireplumber"
fail=0
note() { printf '%s\n' "$*"; }
bad()  { printf 'FAIL: %s\n' "$*"; fail=1; }

# ---------------------------------------------------------------- live report
note "== live session (read-only) =="
if ! command -v wpctl >/dev/null 2>&1; then
  bad "no wpctl on PATH — is pipewire/wireplumber installed on this host?"
else
  note "default sink:   $(wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>&1)"
  note "default source: $(wpctl get-volume @DEFAULT_AUDIO_SOURCE@ 2>&1)"
fi

for f in stream-properties default-routes default-nodes; do
  if [ -e "$STATE/$f" ]; then
    note "state: $f  ($(wc -l < "$STATE/$f") entries, mtime $(date -r "$STATE/$f" '+%F %T'))"
  else
    note "state: $f  (absent — normal until something of that kind changes)"
  fi
done
[ -e "$STATE/stream-properties" ] || [ -e "$STATE/default-routes" ] || \
  bad "no wireplumber state at all under $STATE — nothing can be restored"

# The hooks that do the restoring. Only a config that explicitly disables them
# (the `mixin.stateless` profile, meant for embedded use) breaks this, so what
# we are looking for is an override, anywhere in the config hierarchy.
if command -v wireplumber >/dev/null 2>&1; then
  off=$(grep -rlE '(hooks\.(stream\.state|device\.routes\.state)|node\.stream\.restore-props)[[:space:]]*=[[:space:]]*(disabled|false)' \
        /etc/wireplumber /usr/share/wireplumber ~/.config/wireplumber \
        "$(dirname "$(readlink -f "$(command -v wireplumber)")")/../share/wireplumber" \
        2>/dev/null | grep -v 'wireplumber\.conf$' | sort -u)
  if [ -n "$off" ]; then
    bad "restore hooks disabled by: $off"
  else
    note "restore hooks: no override found (stock = enabled)"
  fi
fi

# --------------------------------------------------------- isolated end-to-end
note ""
note "== isolated restore test (private daemons, live graph untouched) =="
for b in pipewire wireplumber dbus-daemon; do
  command -v "$b" >/dev/null 2>&1 || { bad "no $b on PATH"; exit 1; }
done

mkdir -p "$DIR"/{run,state,config/pipewire/pipewire.conf.d,config/wireplumber/wireplumber.conf.d}
chmod 700 "$DIR/run"
cleanup() {
  kill "${WP_PID:-}" "${PW_PID:-}" "${BUS_PID:-}" 2>/dev/null
  # gvfsd follows the private session bus and fuse-mounts $DIR/run/gvfs, which
  # then makes the directory unremovable. Unmount before deleting.
  fusermount -u "$DIR/run/gvfs" 2>/dev/null || umount "$DIR/run/gvfs" 2>/dev/null
  [ "$KEEP" = 1 ] || rm -rf "$DIR"
}
trap cleanup EXIT

# A null sink is an Audio/Sink with no device.routes — the same restore path
# WirePlumber uses for every virtual/filter sink (easyeffects on both hosts,
# and on book the asahi-audio speaker convolver that IS the default sink).
cat > "$DIR/config/pipewire/pipewire.conf.d/99-voltest.conf" <<'EOF'
context.objects = [
  { factory = adapter
    args = {
      factory.name     = support.null-audio-sink
      node.name        = "voltest"
      node.description = "voltest"
      media.class      = "Audio/Sink"
      audio.position   = "[ FL FR ]"
      object.linger    = true
    }
  }
]
EOF

# Device monitors off: this instance must never open a real card. The asahi
# components only exist on book, and naming a component that does not exist is
# what makes wireplumber abort, so gate them on the file that provides them.
{
  echo 'wireplumber.profiles = {'
  echo '  main = {'
  for c in monitor.alsa monitor.alsa.reserve-device monitor.alsa-midi \
           monitor.bluez monitor.bluez-midi monitor.libcamera monitor.v4l2; do
    echo "    $c = disabled"
  done
  if [ -e /usr/share/wireplumber/wireplumber.conf.d/99-asahi.conf ]; then
    echo '    custom.asahi = disabled'
    echo '    node.software-dsp = disabled'
  fi
  echo '  }'
  echo '}'
} > "$DIR/config/wireplumber/wireplumber.conf.d/99-voltest.conf"

export XDG_RUNTIME_DIR="$DIR/run" XDG_STATE_HOME="$DIR/state" \
       XDG_CONFIG_HOME="$DIR/config" XDG_DATA_HOME="$DIR/data" \
       PIPEWIRE_RUNTIME_DIR="$DIR/run" PIPEWIRE_CORE=voltest PIPEWIRE_REMOTE=voltest
unset PULSE_RUNTIME_PATH PULSE_SERVER

dbus-daemon --session --fork --address="unix:path=$DIR/bus" >/dev/null 2>&1
export DBUS_SESSION_BUS_ADDRESS="unix:path=$DIR/bus"

start_daemons() {
  pipewire     >>"$DIR/pw.log" 2>&1 & PW_PID=$!
  sleep 2
  wireplumber  >>"$DIR/wp.log" 2>&1 & WP_PID=$!
  sleep 3
}
stop_daemons() {
  kill "$WP_PID" 2>/dev/null; sleep 1
  kill "$PW_PID" 2>/dev/null; sleep 1
}

start_daemons
if ! wpctl status >/dev/null 2>&1; then
  bad "private instance did not come up — see $DIR/pw.log and $DIR/wp.log"
  KEEP=1; exit 1
fi

wpctl set-volume @DEFAULT_AUDIO_SINK@ 42% || bad "could not set the test volume"
sleep 2
before=$(wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>&1)
note "set:            $before"
saved=$(grep -h voltest "$DIR/state/wireplumber/stream-properties" 2>/dev/null)
[ -n "$saved" ] || bad "nothing written to the private stream-properties"
note "saved:          ${saved:-<nothing>}"

stop_daemons
start_daemons
after=$(wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>&1)
note "after restart:  $after"

case "$after" in
  *0.42*) note "" ; note "RESULT: this host restores a sink volume across a daemon restart." ;;
  *)      bad "volume did NOT come back (wanted 0.42, got '$after')" ;;
esac

[ "$fail" = 0 ] || note ""
[ "$fail" = 0 ] && note "OK" || note "one or more checks FAILED"
exit "$fail"
