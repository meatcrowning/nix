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
python=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["python"])' "$package/libexec/unity-quantal/config.json")
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
# Tweak Tool's inventory runs in the original runtime, which sees only the home.
cp "$repo/tools/unity-tweaks-inventory.py" "$run/home/tweaks-inventory.py"
cp "$repo/tools/unity-tweaks-check.py" "$run/tweaks-check.py"
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
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gsettings get \
  org.gnome.nautilus.preferences thumbnail-limit | grep -qx 'uint64 1073741824'
# Exercise Files' original thumbnail factory with refreshed providers, including
# their subprocesses under the legacy library and pixbuf environment.
mkdir -p "$HOME/thumbnail-probes"
magick -size 320x180 xc:steelblue "$HOME/thumbnail-probes/image.png"
magick "$HOME/thumbnail-probes/image.png" "$HOME/thumbnail-probes/image.jpg"
ffmpeg -nostdin -v error -f lavfi -i color=c=blue:s=320x180:d=1 \
  -an -c:v libx264 -pix_fmt yuv420p "$HOME/thumbnail-probes/video.mp4"
"$UNITY_BASE_PACKAGE/bin/unity-quantal-runtime" "$TEST_PYTHON" -c '
import ctypes, pathlib
desktop = ctypes.CDLL("libgnome-desktop-3.so.4")
glib = ctypes.CDLL("libgobject-2.0.so.0")
pixbuf = ctypes.CDLL("libgdk_pixbuf-2.0.so.0")
glib.g_type_init()
desktop.gnome_desktop_thumbnail_factory_new.argtypes = [ctypes.c_int]
desktop.gnome_desktop_thumbnail_factory_new.restype = ctypes.c_void_p
desktop.gnome_desktop_thumbnail_factory_can_thumbnail.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_long]
desktop.gnome_desktop_thumbnail_factory_generate_thumbnail.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
desktop.gnome_desktop_thumbnail_factory_generate_thumbnail.restype = ctypes.c_void_p
desktop.gnome_desktop_thumbnail_factory_save_thumbnail.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long]
desktop.gnome_desktop_thumbnail_factory_lookup.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long]
desktop.gnome_desktop_thumbnail_factory_lookup.restype = ctypes.c_char_p
pixbuf.gdk_pixbuf_get_width.argtypes = [ctypes.c_void_p]
pixbuf.gdk_pixbuf_get_height.argtypes = [ctypes.c_void_p]
glib.g_object_unref.argtypes = [ctypes.c_void_p]
factory = desktop.gnome_desktop_thumbnail_factory_new(0)
for name, mime in [("image.png", "image/png"), ("image.jpg", "image/jpeg"), ("video.mp4", "video/mp4")]:
    file = pathlib.Path.home() / "thumbnail-probes" / name
    uri, mime = file.as_uri().encode(), mime.encode()
    mtime = int(file.stat().st_mtime)
    assert desktop.gnome_desktop_thumbnail_factory_can_thumbnail(factory, uri, mime, mtime), name
    thumb = desktop.gnome_desktop_thumbnail_factory_generate_thumbnail(factory, uri, mime)
    assert thumb, name
    assert 0 < pixbuf.gdk_pixbuf_get_width(thumb) <= 128, name
    assert 0 < pixbuf.gdk_pixbuf_get_height(thumb) <= 128, name
    desktop.gnome_desktop_thumbnail_factory_save_thumbnail(factory, thumb, uri, mtime)
    assert desktop.gnome_desktop_thumbnail_factory_lookup(factory, uri, mtime), name
    glib.g_object_unref(thumb)
glib.g_object_unref(factory)
print("PASS: original Files factory generates and caches PNG, JPEG and H.264 video previews")
'
if [ "${UNITY_TEST_PREVIEWS_ONLY:-0}" = 1 ]; then
  exit 0
fi
"$UNITY_PACKAGE/bin/unity-quantal-mouse" unity
grep -qx unity /home/unity-test/.config/unity-quantal/mouse-profile
"$UNITY_PACKAGE/bin/unity-quantal-mouse" plasma
grep -qx plasma /home/unity-test/.config/unity-quantal/mouse-profile
kill -0 "$supervisor"
"$UNITY_PACKAGE/bin/unity-quantal-runtime" "$TEST_PYTHON" -c '
import ctypes
lib=ctypes.CDLL("libgio-2.0.so.0")
lib.g_type_init()
lib.g_app_info_get_default_for_type.argtypes=[ctypes.c_char_p,ctypes.c_int]
lib.g_app_info_get_default_for_type.restype=ctypes.c_void_p
lib.g_app_info_get_id.argtypes=[ctypes.c_void_p]
lib.g_app_info_get_id.restype=ctypes.c_char_p
for mime,app in [(b"text/plain",b"gedit"),(b"image/png",b"eog"),(b"application/zip",b"file-roller")]:
    info=lib.g_app_info_get_default_for_type(mime,0)
    assert info and lib.g_app_info_get_id(info)==b"unity-original-"+app+b".desktop",mime
print("PASS: original GLib resolves all three Unity document defaults")
'
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/local/bin/unity-host-launch --desktop unity-original-gcalctool.desktop -- "$UNITY_PACKAGE/bin/unity-quantal-isolated" gcalctool
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
for app in Gnome-terminal Gnome-control-center; do
  grep "$app" /work/tree.txt
done
calculator=$(while read -r wid title rest; do
  if [[ "$rest" == *'"Gcalctool"'* ]]; then echo "$wid"; break; fi
done < /work/tree.txt)
xprop -id "$calculator" _NET_WM_DESKTOP_FILE | grep unity-original-gcalctool.desktop
application=$(gdbus call --session --dest org.ayatana.bamf --object-path /org/ayatana/bamf/matcher --method org.ayatana.bamf.matcher.ApplicationForXid "$((calculator))")
application=${application#*\'}
application=${application%%\'*}
gdbus call --session --dest org.ayatana.bamf --object-path "$application" --method org.ayatana.bamf.application.DesktopFile | grep unity-original-gcalctool.desktop
# Meta drags windows: left moves, right resizes; Alt drags reach the client.
# The window tree can change mid-listing while windows open; retry on the next poll.
window_id() { { xwininfo -root -tree 2>/dev/null || true; } | sed -n "s/^ *\\(0x[0-9a-f]*\\) $1.*/\\1/p" | head -n1; }
probe=$(window_id '"unity-host-probe"')
terminal=$(window_id '"Terminal".*736x457')
test -n "$probe" && test -n "$terminal"
geometry() { xwininfo -id "$target" | sed -n 's/.*\(Absolute upper-left [XY]\|Width\|Height\): *//p' | tr '\n' ' '; echo; }
drag() {
  local key=$1 button=$2 x y width height
  # Another window may overlap the grab point; drag the target from the top.
  xdotool windowraise "$target" sleep 0.3
  read -r x y width height < <(geometry)
  # Grab the lower-right quarter: Compiz resizes the edges nearest the pointer.
  xdotool mousemove $((x + width * 3 / 4)) $((y + height * 3 / 4)) sleep 0.2 keydown "$key" sleep 0.2 \
    mousedown "$button" sleep 0.2 mousemove_relative -- 60 50 sleep 0.2 mousemove_relative -- 60 50 \
    sleep 0.2 mouseup "$button" sleep 0.2 keyup "$key" sleep 0.5
  read -r X Y W H < <(geometry)
  echo "$key+$button: $x $y $width $height -> $X $Y $W $H" | tee -a /work/drag.txt
  dx=$((X - x)) dy=$((Y - y)) dw=$((W - width)) dh=$((H - height))
}
target=$probe
drag Alt_L 1
test "$dx $dy" = "0 0"
drag Super_L 1
test "$dx" -ge 100 && test "$dy" -ge 80 && test "$dw $dh" = "0 0"
# xmessage is fixed-size; resize a terminal instead.
target=$terminal
drag Super_L 3
test "$dw" -gt 0 || test "$dh" -gt 0
echo 'PASS: Meta+left moves, Meta+right resizes, Alt+left leaves windows in place'
# Appearance offers Ambiance Dark (the uninstalled High Contrast entries stay
# hidden); choosing a theme restyles running apps.
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gnome-control-center background >/work/appearance.log 2>&1 &
for _ in {1..60}; do
  appearance=$(window_id '"Appearance"')
  [ -n "$appearance" ] && break
  sleep 0.1
done
test -n "$appearance"
sleep 2
target=$appearance
read -r ax ay _ _ < <(geometry)
theme() { "$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gsettings get org.gnome.desktop.interface gtk-theme; }
background() { import -silent -window root -crop 1x1+$((ax + 100))+$((ay + 270)) -format '%[fx:int(255*luminance)]' info:; }
pick() {
  xdotool mousemove $((ax + 685)) $((ay + 467)) click 1 sleep 0.5 key "$@" sleep 0.3 key Return sleep 1
}
# Restyling every running GTK window takes a moment; poll rather than guess.
restyled() {
  for _ in {1..30}; do
    [ "$(background)" "$1" "$2" ] && return 0
    sleep 0.2
  done
  return 1
}
test "$(theme)" = "'Ambiance-Dark'"
restyled -lt 80
pick Up Up
test "$(theme)" = "'Ambiance'"
restyled -gt 200
pick Down Down
test "$(theme)" = "'Ambiance-Dark'"
restyled -lt 80
echo 'PASS: Appearance switches between Ambiance and Ambiance Dark live'
# Brightness keys and night light share one gamma ramp; the panel opens from
# original Settings and the indicator sits in the original panel.
display_state=/home/unity-test/.config/unity-quantal/display.json
gdbus call --session --dest com.canonical.indicator.application \
  --object-path /com/canonical/indicator/application/service \
  --method com.canonical.indicator.application.service.GetApplications > /work/indicators.txt
grep unity-quantal-display /work/indicators.txt
xdotool key XF86MonBrightnessDown sleep 0.3 key XF86MonBrightnessDown sleep 0.5
grep '"brightness": 90' "$display_state"
xrandr --verbose > /work/xrandr-dim.txt
if grep -q 'Gamma:' /work/xrandr-dim.txt; then grep 'Brightness: 0.9' /work/xrandr-dim.txt; fi
printf '{"brightness": 90, "night": true, "temperature": 3500}' > "$display_state.tmp"
mv "$display_state.tmp" "$display_state"
sleep 1
xrandr --verbose > /work/xrandr-night.txt
if grep -q 'Gamma:' /work/xrandr-night.txt; then ! grep 'Gamma: *1.0:1.0:1.0' /work/xrandr-night.txt; fi
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gnome-control-center unity-host-display >/work/display-panel.log 2>&1 &
for _ in {1..150}; do
  display_panel=$(window_id '"Brightness & Night Light"')
  [ -n "$display_panel" ] && break
  sleep 0.1
done
test -n "$display_panel"
for _ in {1..50}; do
  xprop -id "$display_panel" _NET_WM_DESKTOP_FILE | grep -q unity-display.desktop && break
  sleep 0.1
done
xprop -id "$display_panel" _NET_WM_DESKTOP_FILE | grep unity-display.desktop
sleep 1
import -silent -window root /work/display-panel.png
xdotool key XF86MonBrightnessUp sleep 0.5
grep '"brightness": 95' "$display_state"
grep '"night": true' "$display_state"
echo 'PASS: brightness keys, night light state, indicator, and Settings panel'
# Scrolling the panel icon steps brightness both ways (Unity sends +120 per
# notch up, -120 down).
printf '{"brightness": 50, "night": true, "temperature": 3500}' > "$display_state.tmp"
mv "$display_state.tmp" "$display_state"
sleep 1
display_entry=$(gdbus call --session --dest com.canonical.Unity.Panel.Service --object-path /com/canonical/Unity/Panel/Service \
  --method com.canonical.Unity.Panel.Service.Sync | grep -o "'libapplication.so', '0x[0-9a-f]*', 'unity-quantal-display'" | sed "s/.*'\(0x[0-9a-f]*\)'.*/\1/")
test -n "$display_entry"
scroll_entry() { gdbus call --session --dest com.canonical.Unity.Panel.Service --object-path /com/canonical/Unity/Panel/Service \
  --method com.canonical.Unity.Panel.Service.ScrollEntry -- "$display_entry" "$1" >/dev/null; sleep 0.5; }
scroll_entry 120
grep '"brightness": 55' "$display_state"
scroll_entry -120
grep '"brightness": 50' "$display_state"
echo 'PASS: scrolling the panel indicator steps brightness up and down'
# A live refresh replaces the display service and keeps it registered.
display_owner() { gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
  --method org.freedesktop.DBus.GetConnectionUnixProcessID org.unity_quantal.Display 2>/dev/null || true; }
before=$(display_owner)
test -n "$before"
"$UNITY_PACKAGE/bin/unity-quantal-refresh" >/work/display-refresh.log 2>&1
for _ in {1..50}; do
  after=$(display_owner)
  [ -n "$after" ] && [ "$after" != "$before" ] && break
  sleep 0.1
done
test -n "$after" && test "$after" != "$before"
echo 'PASS: unity-quantal-refresh replaces the live display service'
# CPU frequency and weather indicators. The test has no network: the fetcher,
# run on the host side through the launch socket, reports the service down;
# a fixture report then fills the panel entry.
indicators() { gdbus call --session --dest com.canonical.indicator.application \
  --object-path /com/canonical/indicator/application/service \
  --method com.canonical.indicator.application.service.GetApplications; }
for _ in {1..50}; do
  indicators > /work/indicators.txt
  grep -q "indicator-cpufreq-[0-9]*'" /work/indicators.txt && grep -q unity-quantal-weather /work/indicators.txt && break
  sleep 0.1
done
grep -o "'indicator-cpufreq-[0-9]*'" /work/indicators.txt
weather_settings=/home/unity-test/.config/unity-quantal/weather.json
weather_report=/home/unity-test/.cache/unity-quantal/weather.json
printf '{"location": "Testville", "units": "metric"}' > "$weather_settings.tmp"
mv "$weather_settings.tmp" "$weather_settings"
for _ in {1..100}; do
  grep -q 'Weather service unavailable' "$weather_report" 2>/dev/null && break
  sleep 0.1
done
grep '"query": "Testville"' "$weather_report"
grep 'Weather service unavailable' "$weather_report"
printf '{"query": "Testville", "fetched": %s, "place": {"name": "Testville", "latitude": 0, "longitude": 0},
  "forecast": {"current": {"temperature_2m": 23.4, "apparent_temperature": 22, "relative_humidity_2m": 40,
  "weather_code": 61, "wind_speed_10m": 9, "wind_direction_10m": 200, "is_day": 1},
  "daily": {"time": ["2026-10-10", "2026-10-11"], "weather_code": [61, 0], "temperature_2m_max": [24, 20],
  "temperature_2m_min": [15, 12], "sunrise": ["2026-10-10T07:40", "2026-10-11T07:41"],
  "sunset": ["2026-10-10T19:05", "2026-10-11T19:03"]}}}' "$(date +%s)" > "$weather_report.tmp"
mv "$weather_report.tmp" "$weather_report"
for _ in {1..50}; do
  indicators > /work/indicators.txt
  grep -q "'weather-showers-scattered'.*'23°'" /work/indicators.txt && break
  sleep 0.1
done
grep -o "'weather-showers-scattered'.*'23°'" /work/indicators.txt
echo 'PASS: CPU frequency meter and weather indicator, fetch through the host launcher'
# Quantal's Nautilus extensions load into the original Files.
gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
  --method org.freedesktop.DBus.StartServiceByName org.gnome.Nautilus 0
files=$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
  --method org.freedesktop.DBus.GetConnectionUnixProcessID org.gnome.Nautilus | grep -o '[0-9]*' | tail -n1)
for _ in {1..50}; do
  grep -q libnautilus-python /proc/"$files"/maps && break
  sleep 0.1
done
for extension in actions-menu image-converter python; do
  grep -q "libnautilus-$extension.so" /proc/"$files"/maps
done
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/python2.7 -c '
from gi.repository import Nautilus
scope = {"__name__": "nautilus_compare"}
execfile("/usr/share/nautilus-python/extensions/nautilus-compare.py", scope)
assert any(isinstance(v, type) and issubclass(v, Nautilus.MenuProvider) for v in scope.values())
'
# Meld is PyGTK 2; keep it out of the GTK 3 process above.
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/python2.7 -c 'import gtk.glade'
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/convert -version | grep 'ImageMagick 6.7.7'
test -f "$session_dir/applications/unity-original-nact.desktop"
echo 'PASS: Nautilus Actions, Image Converter and Compare load in original Files'
indicator_owner() { gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
  --method org.freedesktop.DBus.GetConnectionUnixProcessID "$1" 2>/dev/null || true; }
cpufreq_before=$(indicator_owner org.unity_quantal.CpuFreq)
weather_before=$(indicator_owner org.unity_quantal.Weather)
test -n "$cpufreq_before" && test -n "$weather_before"
"$UNITY_PACKAGE/bin/unity-quantal-refresh" >/work/indicator-refresh.log 2>&1
for _ in {1..50}; do
  cpufreq_after=$(indicator_owner org.unity_quantal.CpuFreq)
  weather_after=$(indicator_owner org.unity_quantal.Weather)
  [ -n "$cpufreq_after" ] && [ "$cpufreq_after" != "$cpufreq_before" ] &&
    [ -n "$weather_after" ] && [ "$weather_after" != "$weather_before" ] && break
  sleep 0.1
done
test -n "$cpufreq_after" && test "$cpufreq_after" != "$cpufreq_before"
test -n "$weather_after" && test "$weather_after" != "$weather_before"
echo 'PASS: unity-quantal-refresh replaces the CPU frequency and weather indicators'
# The session terminal is GNOME Terminal 3.6's window over the current VTE.
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/local/bin/x-terminal-emulator -e "$UNITY_TEST_TOOLS/bin/bash" \
  -c 'printf "\e[40m  \e[0m\n"; sleep 30' >/work/terminal-session.log 2>&1 &
for _ in {1..80}; do
  target=$(window_id '"[^"]*": ("unity-terminal"')
  [ -n "$target" ] && break
  sleep 0.1
done
test -n "$target"
sleep 2
import -silent -window "$target" /work/terminal-session.png
pixel() { magick /work/terminal-session.png -crop 1x1+$1+$2 -depth 8 -format '%[hex:p{0,0}]' info:; }
test "$(pixel 300 8)" = 3C3B37
top=0
while [ "$(pixel 400 $top)" != 300A24 ]; do top=$((top + 1)); [ $top -lt 60 ]; done
test "$(pixel 400 300)" = 300A24
test "$(pixel 5 $((top + 8)))" = 000000
echo 'PASS: Unity terminal opens with the 12.10 menubar and screen'
# GNOME Tweak Tool: every key it shows is mapped to a reader in tweaks.json,
# and each automatic check reaches that reader.
test -f "$session_dir/applications/unity-original-gnome-tweak-tool.desktop"
tweak_map="$UNITY_PACKAGE/libexec/unity-quantal/tweaks.json"
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/python2.7 /home/unity-test/tweaks-inventory.py \
  > /work/tweaks-inventory.json 2>/work/tweaks-inventory.log
"$TEST_PYTHON" /work/tweaks-check.py "$UNITY_PACKAGE" "$tweak_map" /work/tweaks-inventory.json | tee /work/tweaks-check.txt
tweak() { "$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/bin/gsettings "$@"; }
active() { xprop -root _NET_ACTIVE_WINDOW | grep -o '0x[0-9a-f]*'; }
extents() { xprop -id "$1" _NET_FRAME_EXTENTS | sed 's/.*= //'; }
"$UNITY_TEST_TOOLS/bin/xmessage" -name tweak-probe-a -geometry 300x120+200+200 a >/dev/null 2>&1 &
"$UNITY_TEST_TOOLS/bin/xmessage" -name tweak-probe-b -geometry 300x120+900+500 b >/dev/null 2>&1 &
for _ in {1..50}; do
  probe_a=$(window_id '"tweak-probe-a"'); probe_b=$(window_id '"tweak-probe-b"')
  [ -n "$probe_a" ] && [ -n "$probe_b" ] && break
  sleep 0.1
done
test -n "$probe_a" && test -n "$probe_b"
sleep 1
# Titlebar font: the decoration grows with it.
for _ in {1..50}; do extents "$probe_a" | grep -q '^[0-9]' && break; sleep 0.1; done
before=$(extents "$probe_a")
tweak set org.gnome.desktop.wm.preferences titlebar-font "'Ubuntu Bold 28'"
for _ in {1..40}; do [ "$(extents "$probe_a")" != "$before" ] && break; sleep 0.1; done
after=$(extents "$probe_a")
tweak reset org.gnome.desktop.wm.preferences titlebar-font
echo "titlebar-font: $before -> $after"
test "$(echo "$after" | cut -d, -f3)" -gt "$(echo "$before" | cut -d, -f3)"
echo 'PASS: titlebar-font reaches the window decorations'
# Focus mode: with sloppy focus, pointing at a window focuses it.
xdotool windowactivate --sync "$probe_a" sleep 0.5
tweak set org.gnome.desktop.wm.preferences focus-mode "'sloppy'"
sleep 1
xdotool mousemove 1050 560 sleep 1
sloppy=$(active)
tweak reset org.gnome.desktop.wm.preferences focus-mode
sleep 1
xdotool mousemove 350 260 sleep 1
clicked=$(active)
echo "focus-mode: probes $probe_a $probe_b; sloppy -> $sloppy; click -> $clicked"
test "$((sloppy))" = "$((probe_b))" && test "$((clicked))" = "$((probe_b))"
echo 'PASS: focus-mode reaches Compiz'
# Titlebar double-click action: minimize instead of maximize.
tweak set org.gnome.desktop.wm.preferences action-double-click-titlebar "'minimize'"
sleep 1
xdotool windowactivate --sync "$probe_a" sleep 0.5
target=$probe_a
read -r x y width _ < <(geometry)
top=$(extents "$probe_a" | cut -d, -f3)
xdotool mousemove $((x + width / 2)) $((y - top / 2)) sleep 0.3 click --repeat 2 --delay 80 1 sleep 1
xprop -id "$probe_a" _NET_WM_STATE | tee /work/titlebar-state.txt
tweak reset org.gnome.desktop.wm.preferences action-double-click-titlebar
grep -q _NET_WM_STATE_HIDDEN /work/titlebar-state.txt
xdotool windowactivate --sync "$probe_a" 2>/dev/null || true
echo 'PASS: action-double-click-titlebar reaches the window decorations'
# Desktop icons: Files' desktop window follows show-desktop-icons.
desktop_windows() { for w in $(xprop -root _NET_CLIENT_LIST | grep -o '0x[0-9a-f]*'); do
  xprop -id "$w" _NET_WM_WINDOW_TYPE | grep -q DESKTOP && echo "$w"; done; true; }
desktop_windows > /work/desktop-before.txt
tweak set org.gnome.desktop.background show-desktop-icons false
for _ in {1..50}; do [ -z "$(desktop_windows)" ] && break; sleep 0.1; done
desktop_windows > /work/desktop-hidden.txt
tweak reset org.gnome.desktop.background show-desktop-icons
echo "desktop windows: $(wc -l < /work/desktop-before.txt) -> $(wc -l < /work/desktop-hidden.txt)"
test -s /work/desktop-before.txt && test ! -s /work/desktop-hidden.txt
echo 'PASS: show-desktop-icons reaches the Files desktop'
# Workspaces: Unity's are Compiz's viewport grid; num-workspaces stays inert,
# as tweaks.json records. A change here means the map needs a real reader.
xprop -root _NET_NUMBER_OF_DESKTOPS _NET_DESKTOP_GEOMETRY > /work/workspaces-before.txt
tweak set org.gnome.desktop.wm.preferences num-workspaces 3
sleep 2
xprop -root _NET_NUMBER_OF_DESKTOPS _NET_DESKTOP_GEOMETRY > /work/workspaces-after.txt
tweak reset org.gnome.desktop.wm.preferences num-workspaces
test "$(cat /work/workspaces-before.txt)" = "$(cat /work/workspaces-after.txt)"
echo 'PASS: num-workspaces stays inert in Unity, as tweaks.json records'
# Monospace font: the session terminal follows it, live.
tweak set org.gnome.desktop.interface monospace-font-name "'Ubuntu Mono 13'"
"$UNITY_PACKAGE/bin/unity-quantal-runtime" /usr/local/bin/x-terminal-emulator -e "$UNITY_TEST_TOOLS/bin/bash" \
  -c 'while :; do stty size > "$HOME/terminal-size.tmp"; mv "$HOME/terminal-size.tmp" "$HOME/terminal-size"; sleep 0.2; done' \
  >/work/terminal-font.log 2>&1 &
for _ in {1..80}; do [ -s "$HOME/terminal-size" ] && break; sleep 0.1; done
small=$(cat "$HOME/terminal-size")
tweak set org.gnome.desktop.interface monospace-font-name "'Ubuntu Mono 26'"
for _ in {1..50}; do [ "$(cat "$HOME/terminal-size")" != "$small" ] && break; sleep 0.1; done
large=$(cat "$HOME/terminal-size")
tweak reset org.gnome.desktop.interface monospace-font-name
echo "terminal rows/columns: $small -> $large"
test "${large#* }" -lt "${small#* }"
echo 'PASS: monospace-font-name reaches the session terminal live'
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
"$test_tools/bin/timeout" --kill-after=5s 180s "$test_tools/bin/bwrap" --die-with-parent --new-session --unshare-all \
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
  --setenv UNITY_PACKAGE "$package" --setenv TEST_PYTHON "$python" --setenv UNITY_TEST_TOOLS "$test_tools" \
  --setenv UNITY_BASE_PACKAGE "${UNITY_BASE_PACKAGE:-$package}" \
  --setenv UNITY_TEST_PREVIEWS_ONLY "${UNITY_TEST_PREVIEWS_ONLY:-0}" \
  --chdir /work "$test_tools/bin/bash" /work/inside.sh
