#!/usr/bin/env bash
# Headless session test. The outer namespace has no host display, bus, audio,
# home, input devices, or systemd user-manager socket.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
export QT_QPA_PLATFORM=offscreen
source "$repo/tools/lib/session-guard.sh"
sg_require_offscreen
if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "usage: tools/unity-quantal-test.sh SESSION_PACKAGE TEST_TOOLS [RENDER_NODE]" >&2
  exit 2
fi
package=$1
test_tools=$2
graphics=(--setenv LIBGL_ALWAYS_SOFTWARE 1)
if [ "$#" -eq 3 ]; then
  if [[ ! "$3" =~ ^/dev/dri/renderD[0-9]+$ ]] || [ ! -c "$3" ]; then
    echo 'Expected a render-only DRM node' >&2
    exit 2
  fi
  graphics=(--dev-bind "$3" "$3" --setenv UNITY_TEST_ACCELERATED 1)
fi
run=$(mktemp -d /tmp/unity-session-test.XXXXXX)
mkdir -p "$run/home/.local/share/applications" "$run/home/.config"
mkdir -p "$run/home/.local/share/icons/hicolor/scalable/apps"
cat > "$run/home/.local/share/icons/hicolor/scalable/apps/unity-quantal-probe.svg" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"><rect width="96" height="96" fill="#3498db"/></svg>
SVG
printf '[Default Applications]\ninode/directory=unity-quantal-probe.desktop\n' > "$run/home/.config/mimeapps.list"
printf 'root:x:0:0:root:/root:/bin/sh\nunity-test:x:%s:%s:Unity Test:/home/unity-test:/bin/sh\n' "$(id -u)" "$(id -g)" > "$run/passwd"
printf 'users:x:%s:unity-test\n' "$(id -g)" > "$run/group"
printf 'passwd: files\ngroup: files\nhosts: files dns\n' > "$run/nsswitch.conf"
printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' > "$run/machine-id"
printf 'nameserver 127.0.0.1\n' > "$run/resolv.conf"
mkdir -p "$run/profile/bin"
printf '#!%s/bin/bash\necho native-command-found\n' "$test_tools" > "$run/profile/bin/unity-host-cli"
cat > "$run/home/host-shell" <<'SHELL'
#!/bin/bash
unity-host-cli > "$HOME/terminal-command-result"
exec /bin/bash "$@"
SHELL
chmod +x "$run/profile/bin/unity-host-cli" "$run/home/host-shell"
sed -i "1c#!$test_tools/bin/bash" "$run/home/host-shell"
sed -i "s|exec /bin/bash|exec $test_tools/bin/bash|" "$run/home/host-shell"
if command -v codex >/dev/null; then
  ln -s "$(readlink -f "$(command -v codex)")" "$run/profile/bin/codex"
  sed -i '/unity-host-cli/a codex --version > "$HOME/terminal-codex-version"' "$run/home/host-shell"
fi
cat > "$run/home/.local/share/applications/unity-quantal-probe.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Unity Host Launch Probe
Icon=unity-quantal-probe
Exec=$test_tools/bin/xmessage -name unity-host-probe -buttons ok:0 host-application
Terminal=false
EOF
cat > "$run/inside.sh" <<'EOF'
set -euo pipefail
source /guard.sh
sg_require_offscreen
mkdir -p "$XDG_RUNTIME_DIR" /tmp/.X11-unix
chmod 700 "$XDG_RUNTIME_DIR"
trap 'kill $(jobs -pr) 2>/dev/null || true; wait || true' EXIT
mkdir -p /run/dbus
cat > /work/system-bus.conf <<'BUS'
<busconfig><type>system</type><listen>unix:path=/run/dbus/system_bus_socket</listen><auth>EXTERNAL</auth><policy context="default"><allow send_destination="*"/><allow receive_sender="*"/><allow own="*"/></policy></busconfig>
BUS
dbus-daemon --nofork --config-file=/work/system-bus.conf >/work/system-bus.log 2>&1 &
if [ "${UNITY_TEST_ACCELERATED:-0}" = 1 ]; then
  weston --backend=headless --renderer=gl --no-config --shell=kiosk-shell.so \
    --socket=unity-test --width=1920 --height=1080 --fake-seat --idle-time=0 \
    --log=/work/weston.log >/work/weston-err.log 2>&1 &
  weston_pid=$!
  for _ in {1..100}; do
    test -S "$XDG_RUNTIME_DIR/unity-test" && break
    kill -0 "$weston_pid"
    sleep 0.05
  done
  WAYLAND_DISPLAY=unity-test Xwayland :93 -geometry 1920x1080 -nolisten tcp -ac -noreset > /work/xserver.log 2>&1 &
else
  Xvfb :93 -screen 0 1920x1080x24 -nolisten tcp -ac +extension GLX +extension Composite > /work/xserver.log 2>&1 &
fi
xpid=$!
export DISPLAY=:93
for _ in {1..100}; do
  test -S /tmp/.X11-unix/X93 && break
  kill -0 "$xpid"
  sleep 0.05
done
xdpyinfo > /work/display.txt
glxinfo -B > /work/graphics.txt
if [ "${UNITY_TEST_ACCELERATED:-0}" = 1 ]; then
  grep 'Accelerated: yes' /work/graphics.txt
fi
"$UNITY_BASE_PACKAGE/bin/unity-quantal-session" >/work/supervisor.log 2>&1 &
supervisor=$!
for _ in {1..200}; do
  session_dir=$(find "$XDG_RUNTIME_DIR/unity-quantal-session" -name state.json -printf '%h\n' 2>/dev/null | head -n1 || true)
  if [ -n "$session_dir" ] && [ -S "$session_dir/launch.sock" ]; then break; fi
  kill -0 "$supervisor"
  sleep 0.1
done
test -S "$session_dir/launch.sock"
export UNITY_QUANTAL_SESSION_DIR="$session_dir"
export UNITY_QUANTAL_HOST_SOCKET="$session_dir/launch.sock"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$session_dir/bus"
for _ in {1..60}; do
  if gdbus call --timeout 1 --session --dest org.gnome.SessionManager --object-path /org/gnome/SessionManager --method org.gnome.SessionManager.IsSessionRunning 2>/dev/null | grep -q true; then break; fi
  kill -0 "$supervisor"
  sleep 0.1
done
gdbus call --session --dest org.gnome.SessionManager --object-path /org/gnome/SessionManager --method org.gnome.SessionManager.IsSessionRunning | grep true
"$UNITY_BASE_PACKAGE/bin/unity-quantal-runtime" /usr/local/bin/unity-host-launch --desktop unity-quantal-probe.desktop -- "$UNITY_TEST_TOOLS/bin/xmessage" -name unity-host-probe -buttons ok:0 host-application
sleep 3
export XDG_CURRENT_DESKTOP=Unity XDG_SESSION_TYPE=x11
"$UNITY_PACKAGE/bin/unity-quantal-refresh"
test -f /home/unity-test/.local/share/unity-quantal-session/icons/hicolor/96x96/apps/unity-quantal-probe.png
"$UNITY_PACKAGE/bin/unity-quantal-mouse" unity
grep -qx unity /home/unity-test/.config/unity-quantal/mouse-profile
"$UNITY_PACKAGE/bin/unity-quantal-mouse" plasma
grep -qx plasma /home/unity-test/.config/unity-quantal/mouse-profile
kill -0 "$supervisor"
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/local/bin/unity-host-launch --desktop unity-original-gcalctool.desktop -- "$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gcalctool
for app in gedit eog file-roller; do
  "$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/local/bin/unity-host-launch --desktop "unity-original-$app.desktop" -- "$UNITY_PACKAGE/bin/unity-quantal-runtime" "/usr/bin/$app"
done
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/local/bin/unity-host-launch --desktop unity-original-gnome-terminal.desktop -- "$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gnome-terminal --disable-factory --command=/usr/local/bin/unity-native-shell
for _ in {1..50}; do
  if [ -f "$HOME/terminal-command-result" ]; then break; fi
  sleep 0.1
done
if ! grep -qx native-command-found "$HOME/terminal-command-result"; then
  import -silent -window root /work/terminal-failure.png
  exit 1
fi
rm "$HOME/terminal-command-result"
# The default shell path is also used by new tabs, without --command.
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gnome-terminal --disable-factory >/work/terminal-default.log 2>&1 &
for _ in {1..50}; do
  if [ -f "$HOME/terminal-command-result" ]; then break; fi
  sleep 0.1
done
grep -qx native-command-found "$HOME/terminal-command-result"
echo 'PASS: native command lookup through explicit and default terminal shells'
if command -v codex >/dev/null; then
  grep -i codex "$HOME/terminal-codex-version"
fi

# Exercise the original overview's external-panel dispatch, with harmless
# native probes in place of controls that require real system hardware.
for panel in network sound-nua printers power screen datetime; do
  entry="$session_dir/applications/gnome-$panel-panel.desktop"
  id=$(sed -n 's/^X-GNOME-Settings-Panel=//p' "$entry")
  case "$id" in unity-host-*) ;; *) exit 1 ;; esac
  cp "$entry" /work/panel-original.desktop
  sed -i "s|^Exec=.*|Exec=/usr/local/bin/unity-host-launch -- $UNITY_TEST_TOOLS/bin/touch /home/unity-test/panel-$panel|" "$entry"
  "$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gnome-control-center "$id" >/work/settings-dispatch.log 2>&1 &
  for _ in {1..50}; do
    if [ -f "$HOME/panel-$panel" ]; then break; fi
    sleep 0.1
  done
  test -f "$HOME/panel-$panel"
  cp /work/panel-original.desktop "$entry"
done
echo 'PASS: original Settings dispatches all six native control panels'
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gnome-control-center unity-host-screen >/work/lock-panel.log 2>&1 &
for _ in {1..50}; do
  if xwininfo -root -tree | grep -q 'Screensaver.*cinnamon-settings'; then break; fi
  sleep 0.1
done
xwininfo -root -tree | grep 'Screensaver.*cinnamon-settings'
echo 'PASS: maintained screen-lock controls open through original Settings'
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gnome-control-center indicator-datetime >/work/clock-panel.log 2>&1 &
for _ in {1..50}; do
  if xwininfo -root -tree | grep -q '"Clock & Calendar"'; then break; fi
  sleep 0.1
done
xwininfo -root -tree | grep '"Clock & Calendar"'
echo 'PASS: restored original clock panel opens'
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/local/bin/unity-host-launch --desktop gnome-control-center.desktop -- "$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gnome-control-center info
gdbus call --session --dest org.freedesktop.Notifications --object-path /org/freedesktop/Notifications --method org.freedesktop.Notifications.Notify unity-test 0 notification-message-im 'Original notification' 'Isolated notification and icon check' '[]' '{}' 1500
sleep 2
import -silent -window root /work/screen.png
xprop -root _NET_SUPPORTING_WM_CHECK _NET_CLIENT_LIST > /work/windows.txt
xwininfo -root -tree > /work/tree.txt
grep 'unity-host-probe' /work/tree.txt
grep -i 'gcalctool' /work/tree.txt
for app in Gedit Eog File-roller Gnome-terminal Gnome-control-center; do
  grep "$app" /work/tree.txt
done
calculator=$(while read -r wid title rest; do
  if [ "$title" = '"Calculator":' ]; then echo "$wid"; break; fi
done < /work/tree.txt)
xprop -id "$calculator" _NET_WM_DESKTOP_FILE | grep unity-original-gcalctool.desktop
application=$(gdbus call --session --dest org.ayatana.bamf --object-path /org/ayatana/bamf/matcher --method org.ayatana.bamf.matcher.ApplicationForXid "$((calculator))")
application=${application#*\'}
application=${application%%\'*}
gdbus call --session --dest org.ayatana.bamf --object-path "$application" --method org.ayatana.bamf.application.DesktopFile | grep unity-original-gcalctool.desktop
gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.ListNames > /work/bus-names.txt
grep 'com.canonical.Unity.Panel.Service' /work/bus-names.txt
grep 'Starting plugin: unityshell' /home/unity-test/.local/state/unity-quantal/session.log
gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.StartServiceByName com.canonical.Unity.Lens.Applications 0
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gsettings get com.canonical.Unity.Launcher favorites | grep unity-quantal-probe
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gsettings set com.canonical.Unity.Launcher favorites "['application://unity-quantal-probe.desktop', 'unity://running-apps', 'unity://devices']"
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gsettings get com.canonical.Unity.Launcher favorites > /work/favorites.txt
grep unity-quantal-probe /work/favorites.txt
test -f /home/unity-test/.config/dconf/unity_quantal
test ! -e /home/unity-test/.config/dconf/user
gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver --method org.gnome.ScreenSaver.Lock
gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver --method org.gnome.ScreenSaver.GetActive | grep true
gdbus call --session --dest org.gnome.SessionManager --object-path /org/gnome/SessionManager --method org.gnome.SessionManager.Logout 1
for _ in {1..150}; do
  kill -0 "$supervisor" 2>/dev/null || break
  sleep 0.1
done
if kill -0 "$supervisor" 2>/dev/null; then
  echo 'Session did not terminate after logout' >&2
  exit 1
fi
wait "$supervisor"
echo 'PASS: original shell, host application, separate settings, native lock, session logout'
EOF
echo "Unity session test logs: $run"
"$test_tools/bin/timeout" --kill-after=5s 120s "$test_tools/bin/bwrap" --die-with-parent --new-session --unshare-all \
  --ro-bind /nix /nix --proc /proc --dev /dev --ro-bind /sys /sys \
  --symlink "$test_tools/bin" /bin \
  --tmpfs /tmp --tmpfs /run --dir /run/user/1000 \
  --bind "$run" /work --bind "$run/home" /home/unity-test \
  --ro-bind "$run/passwd" /etc/passwd --ro-bind "$run/group" /etc/group \
  --ro-bind "$run/nsswitch.conf" /etc/nsswitch.conf \
  --ro-bind "$run/machine-id" /etc/machine-id \
  --ro-bind "$run/resolv.conf" /etc/resolv.conf \
  --ro-bind "$run/profile" /etc/profiles/per-user/unity-test \
  --ro-bind /run/opengl-driver /run/opengl-driver \
  --ro-bind "$repo/tools/lib/session-guard.sh" /guard.sh \
  --clearenv --setenv HOME /home/unity-test --setenv USER unity-test \
  --setenv LOGNAME unity-test --setenv XDG_RUNTIME_DIR /run/user/1000 \
  --setenv XDG_DATA_DIRS "$test_tools/share" \
  --setenv PATH "/etc/profiles/per-user/unity-test/bin:$test_tools/bin" --setenv LANG C.UTF-8 \
  --setenv SHELL /home/unity-test/host-shell \
  --setenv QT_QPA_PLATFORM offscreen "${graphics[@]}" \
  --setenv UNITY_PACKAGE "$package" --setenv UNITY_TEST_TOOLS "$test_tools" \
  --setenv UNITY_BASE_PACKAGE "${UNITY_BASE_PACKAGE:-$package}" \
  --chdir /work "$test_tools/bin/bash" /work/inside.sh
