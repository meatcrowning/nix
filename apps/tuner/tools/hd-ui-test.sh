#!/usr/bin/env bash
set -euo pipefail
python=${1:?Usage: hd-ui-test.sh /path/to/tuner-python}
root=$(cd "$(dirname "$0")/../../.." && pwd)
scratch=$(mktemp -d /tmp/tuner-layout.XXXXXX)
reap() {
	# dbus-run-session leaves activated portals running (the document portal
	# keeps a FUSE mount in the runtime dir); they are ours only if they
	# inherited this run's scratch HOME.
	local pid
	for pid in $(pgrep -u "$(id -u)" || true); do
		tr '\0' '\n' 2>/dev/null <"/proc/$pid/environ" | grep -qxF "HOME=$scratch" && kill "$pid" 2>/dev/null
	done
	kill "${xpid:-}" 2>/dev/null || true
	for _ in {1..20}; do grep -qF " $scratch/runtime/doc " /proc/mounts || break; sleep .1; done
	if grep -qF " $scratch/runtime/doc " /proc/mounts; then
		fusermount3 -u "$scratch/runtime/doc" 2>/dev/null || fusermount -u "$scratch/runtime/doc" 2>/dev/null || true
	fi
	rm -rf "$scratch"
}
trap reap EXIT
Xvfb -displayfd 3 -screen 0 1280x820x24 -nolisten tcp 3>"$scratch/display" >"$scratch/xlog" 2>&1 &
xpid=$!
for n in {1..50}; do [ -s "$scratch/display" ] && break; sleep .1; done
kill -0 "$xpid"
[[ $(cat "$scratch/display") =~ ^[0-9]+$ ]]
export DISPLAY=":$(cat "$scratch/display")" GDK_BACKEND=x11 QT_QPA_PLATFORM=offscreen
unset WAYLAND_DISPLAY DBUS_SESSION_BUS_ADDRESS PULSE_SERVER PIPEWIRE_REMOTE
source "$root/tools/lib/session-guard.sh"
sg_require_offscreen
export TUNER_ISOLATED_UI=1 GTK_USE_PORTAL=0
export HOME="$scratch" XDG_CONFIG_HOME="$scratch/config" XDG_RUNTIME_DIR="$scratch/runtime" TUNER_GQRX_DIR="$scratch/gqrx" NO_AT_BRIDGE=1 PYTHONDONTWRITEBYTECODE=1
mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME"
chmod 700 "$XDG_RUNTIME_DIR"
dbus-run-session -- "$python" "$root/apps/tuner/tools/hd-ui-test.py"
