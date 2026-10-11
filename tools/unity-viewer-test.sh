#!/usr/bin/env bash
# Every app, pixel read, input event and clipboard belongs to this private X server.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
export QT_QPA_PLATFORM=offscreen
source "$repo/tools/lib/session-guard.sh"
sg_require_offscreen
package=${1:?session package}
viewer=${2:?viewer package}
test_tools=${3:?test tools}
python=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["python"])' "$package/libexec/unity-quantal/config.json")
run=$(mktemp -d /tmp/unity-viewer-test.XXXXXX)
mkdir -p "$run/home/.config/gtk-3.0"
printf 'test:x:%s:%s:Test:/home/test:/bin/bash\n' "$(id -u)" "$(id -g)" > "$run/passwd"
printf 'test:x:%s:test\n' "$(id -g)" > "$run/group"
printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' > "$run/machine-id"
cp "$repo/tools/unity-viewer-check.py" "$run/check.py"
cat > "$run/home/.config/gtk-3.0/settings.ini" <<'EOF'
[Settings]
gtk-theme-name=Ambiance-Dark
gtk-icon-theme-name=ubuntu-mono-dark
gtk-font-name=Ubuntu 11
gtk-enable-animations=false
gtk-xft-dpi=98304
gtk-xft-antialias=1
gtk-xft-hinting=1
gtk-xft-hintstyle=hintslight
gtk-xft-rgba=rgb
EOF
cat > "$run/inside.sh" <<'EOF'
set -euo pipefail
source /guard.sh
sg_require_offscreen
mkdir -p /run/user/1000 /tmp/.X11-unix
chmod 700 /run/user/1000
trap 'kill $(jobs -pr) 2>/dev/null || true; wait || true' EXIT
Xvfb :93 -screen 0 1600x1200x24 -nolisten tcp -ac >/work/xserver.log 2>&1 &
export DISPLAY=:93
for _ in {1..100}; do
  test -S /tmp/.X11-unix/X93 && break
  sleep .05
done
cat > /work/bus.conf <<'BUS'
<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen><auth>EXTERNAL</auth><policy context="default"><allow send_destination="*"/><allow receive_sender="*"/><allow own="*"/></policy></busconfig>
BUS
"$TEST_PYTHON" - <<'PY'
import json, os
from pathlib import Path
config = json.loads((Path(os.environ['UNITY_PACKAGE']) / 'libexec/unity-quantal/config.json').read_text())
p = Path('/work/bus.conf')
p.write_text(p.read_text().replace('</busconfig>', '<servicedir>' + config['dconfServices'] + '</servicedir></busconfig>'))
PY
DBUS_SESSION_BUS_ADDRESS=$(dbus-daemon --config-file=/work/bus.conf --fork --print-address --nopidfile)
export DBUS_SESSION_BUS_ADDRESS
"$TEST_PYTHON" /work/check.py "$UNITY_PACKAGE" "$VIEWER_PACKAGE"
EOF
echo "Viewer fixture: $run"
"$test_tools/bin/timeout" --kill-after=5s 300s "$test_tools/bin/bwrap" \
  --die-with-parent --new-session --unshare-all --ro-bind /nix /nix \
  --proc /proc --dev /dev --symlink "$test_tools/bin" /bin --tmpfs /tmp --tmpfs /run \
  --bind "$run" /work --bind "$run/home" /home/test \
  --ro-bind "$run/passwd" /etc/passwd --ro-bind "$run/group" /etc/group \
  --ro-bind "$run/machine-id" /etc/machine-id \
  --ro-bind "$repo/tools/lib/session-guard.sh" /guard.sh \
  --clearenv --setenv HOME /home/test --setenv USER test --setenv LOGNAME test \
  --setenv PATH "$test_tools/bin" --setenv QT_QPA_PLATFORM offscreen \
  --setenv XDG_RUNTIME_DIR /run/user/1000 --setenv XDG_CURRENT_DESKTOP Unity \
  --setenv VIEWER_BENCHMARK "${VIEWER_BENCHMARK:-0}" \
  --setenv UNITY_PACKAGE "$package" --setenv VIEWER_PACKAGE "$viewer" \
  --setenv TEST_PYTHON "$python" --setenv NO_AT_BRIDGE 1 --setenv LANG C.UTF-8 \
  --chdir /work "$test_tools/bin/bash" /work/inside.sh
