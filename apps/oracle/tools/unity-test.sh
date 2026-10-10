#!/usr/bin/env bash
# Every display, bus, home directory and network interface is private to this
# PID/mount namespace. No session supervisor or user-manager import is run.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
export QT_QPA_PLATFORM=offscreen
source "$repo/tools/lib/session-guard.sh"
sg_require_offscreen
package=${1:?usage: unity-test.sh UNITY_PACKAGE}
config="$package/libexec/unity-quantal/config.json"
mapfile -t bins < <(python3 - "$config" <<'PY'
import json,sys
c=json.load(open(sys.argv[1]))
for key in ('bwrap','bash','python','xvfb','dbus','hostPath'):
    print(c[key])
PY
)
qtenv=$(readlink -f "$(command -v oracle-qtenv)")
run=$(mktemp -d /tmp/oracle-unity-test.XXXXXX)
trap 'rc=$?; if [ "$rc" != 0 ]; then cat "$run"/*.log 2>/dev/null || true; fi; rm -rf "$run"' EXIT
mkdir -p "$run/home" "$run/runtime"
chmod 700 "$run/runtime"
cat > "$run/inside.sh" <<'INNER'
set -euo pipefail
source /source/tools/lib/session-guard.sh
sg_require_offscreen
printf 'test:x:1000:1000:Test:/home/test:/bin/bash\nroot:x:0:0:Root:/root:/bin/bash\n' > /etc/passwd
printf 'test:x:1000:\nroot:x:0:\n' > /etc/group
printf '0123456789abcdef0123456789abcdef\n' > /etc/machine-id
mkdir -p /tmp/.X11-unix "$XDG_RUNTIME_DIR/session" "$HOME/.config" "$HOME/.cache" "$HOME/.local/share"
trap 'kill $(jobs -pr) 2>/dev/null || true; wait || true' EXIT
"$XVFB" :93 -screen 0 1280x900x24 -nolisten tcp -ac >/work/xvfb.log 2>&1 &
xpid=$!
for _ in {1..100}; do
  test -S /tmp/.X11-unix/X93 && break
  kill -0 "$xpid"
  sleep .05
done
test -S /tmp/.X11-unix/X93
export DISPLAY=:93
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
cat > /work/bus.conf <<'BUS'
<busconfig><type>session</type><listen>unix:path=/run/user/1000/bus</listen><auth>EXTERNAL</auth><policy context="default"><allow send_destination="*"/><allow receive_sender="*"/><allow own="*"/></policy></busconfig>
BUS
"$DBUS" --config-file=/work/bus.conf --nofork >/work/dbus.log 2>&1 &
for _ in {1..100}; do test -S "$XDG_RUNTIME_DIR/bus" && break; sleep .05; done
test -S "$XDG_RUNTIME_DIR/bus"
export UNITY_QUANTAL_SESSION_DIR="$XDG_RUNTIME_DIR/session"
"$PYTHON" - <<'PY'
import os,sys
from pathlib import Path
sys.path.insert(0, os.environ['PACKAGE']+'/libexec/unity-quantal')
import session
session.prepare(Path(os.environ['UNITY_QUANTAL_SESSION_DIR']), os.environ)
Path('/etc/fonts').mkdir()
Path('/etc/fonts/fonts.conf').write_text('<fontconfig><dir>' + str(session.ROOT / 'usr/share/fonts') + '</dir><cachedir>/home/test/.cache/fontconfig</cachedir></fontconfig>')
PY
"$QTENV" python3 /source/apps/oracle/tools/unity-engine-test.py

INNER
"${bins[0]}" --die-with-parent --new-session --unshare-all \
  --ro-bind /nix /nix --ro-bind /sys /sys --ro-bind "$repo" /source --bind "$run" /work \
  --bind "$run/home" /home/test --ro-bind "$repo" /home/test/nix --bind "$run/runtime" /run/user/1000 \
  --proc /proc --dev /dev --tmpfs /tmp --tmpfs /etc --symlink "$(dirname "${bins[1]}")" /bin \
  --clearenv --setenv HOME /home/test --setenv USER test --setenv LOGNAME test \
  --setenv XDG_RUNTIME_DIR /run/user/1000 --setenv QT_QPA_PLATFORM offscreen \
  --setenv XDG_CURRENT_DESKTOP Unity --setenv LANG C.UTF-8 \
  --setenv PATH "$(dirname "${bins[1]}"):$(dirname "${bins[2]}"):${bins[5]}" \
  --setenv FFMPEG "$(readlink -f "$(command -v ffmpeg)")" \
  --setenv PACKAGE "$package" --setenv PYTHON "${bins[2]}" \
  --setenv XVFB "${bins[3]}" --setenv DBUS "${bins[4]}" --setenv QTENV "$qtenv" \
  --chdir /source "${bins[1]}" /work/inside.sh

if [ -n "${CHATTER_UNITY_SHOT:-}" ]; then
  cp "$run/home/window.png" "$CHATTER_UNITY_SHOT"
fi
