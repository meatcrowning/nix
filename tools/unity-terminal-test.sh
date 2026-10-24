#!/usr/bin/env bash
# Private X server, clipboard, bus and home; never uses the desktop's seat.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
export QT_QPA_PLATFORM=offscreen
source "$repo/tools/lib/session-guard.sh"
sg_require_offscreen
package=${1:?usage: unity-terminal-test.sh UNITY_PACKAGE}
run=$(mktemp -d /tmp/unity-terminal-test.XXXXXX)
trap 'rm -rf "$run"' EXIT
python3 - "$package" "$run" <<'PY'
import json, pathlib, re, shlex, sys
package, run = map(pathlib.Path, sys.argv[1:])
c = json.loads((package/'libexec/unity-quantal/config.json').read_text())
launcher = (package/'bin/unity-quantal-terminal').read_text()
wrapper = pathlib.Path(re.search(r'exec (\S+)/bin/unity-terminal', launcher)[1])/'bin/unity-terminal'
paths = next(p.decode() for p in wrapper.read_bytes().split(b'\0') if p.startswith(b'/nix/store/') and b'/lib/girepository-1.0:' in p)
(run/'env').write_text('\n'.join(k+'='+shlex.quote(v) for k,v in dict(
    BWRAP=c['bwrap'], BASH=c['bash'], PYTHON=c['bridgePython'], XVFB=c['xvfb'],
    TEST_PATH=c['hostPath'], GI_TYPELIB_PATH=paths,
    TEST_PRELOAD=re.search(r'export LD_PRELOAD=([^$\n]+)', launcher)[1],
    TEST_FONTS=str(package/'libexec/unity-quantal/terminal-fonts.conf')).items()))
PY
source "$run/env"
cat > "$run/check.py" <<'PY'
import ctypes, os, sys
from pathlib import Path
from types import SimpleNamespace
assert os.environ['DISPLAY'] == ':93' and os.environ['HOME'] == '/work/home'
sys.path.insert(0, '/source/lib/unity-quantal')
import terminal as T
assert 'LD_PRELOAD' not in os.environ, 'rasterizer leaks into spawned programs'
ft = ctypes.CDLL('libfreetype.so.6')
handle = ctypes.c_void_p()
assert ft.FT_Init_FreeType(ctypes.byref(handle)) == 0
major, minor, patch = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
ft.FT_Library_Version(handle, ctypes.byref(major), ctypes.byref(minor), ctypes.byref(patch))
assert (major.value, minor.value, patch.value) == (2, 4, 10)
ft.FT_Done_FreeType(handle)
app = T.Application([])
app.register(None)
window = T.TerminalWindow(app)
screen = window.add_screen(['/bin/bash', '-c', 'env > /work/child-env; sleep 20'], '/work')
window.show_all()
pastes = []
screen.terminal.paste_text = pastes.append
clipboard = T.Gtk.Clipboard.get(T.Gdk.SELECTION_CLIPBOARD)
clipboard.set_text('Browser text — café\nsecond line', -1)
mods = T.Gdk.ModifierType
for key, state in [(T.Gdk.KEY_V, mods.CONTROL_MASK | mods.SHIFT_MASK),
                   (T.Gdk.KEY_Insert, mods.SHIFT_MASK)]:
    event = T.Gdk.Event.new(T.Gdk.EventType.KEY_PRESS)
    event.keyval, event.state = key, state
    assert screen.terminal.emit('key-press-event', event)
assert not screen.on_key(screen.terminal, SimpleNamespace(keyval=T.Gdk.KEY_c, state=mods.CONTROL_MASK))
finished = []
T.Gtk.drag_finish = lambda *args: finished.append(args)
uris = ['file:///tmp/a%20b', 'file:///tmp/quote%27%24.txt', 'sftp://host/path']
selection = SimpleNamespace(get_uris=lambda: uris)
screen.on_drop(screen.terminal, None, 0, 0, selection, 0, 1)
assert pastes[-1] == "'/tmp/a b' '/tmp/quote'\"'\"'$.txt' sftp://host/path "
assert finished[-1][1:3] == (True, False)
assert screen.terminal.drag_dest_get_target_list().find(T.Gdk.Atom.intern('text/uri-list', False))[0]
loop = T.GLib.MainLoop()
T.GLib.timeout_add(300, lambda: loop.quit())
loop.run()
assert pastes.count('Browser text — café\nsecond line') == 2, pastes
child_env = Path('/work/child-env').read_text().splitlines()
assert 'COLORTERM=truecolor' in child_env and 'TERM=xterm-256color' in child_env
assert not any(line.startswith(('LD_PRELOAD=', '_UNITY_TERMINAL_', 'FONTCONFIG_FILE=')) for line in child_env)
# Exercise actual VTE painting, including true colour and an italic/bold face.
screen.terminal.feed(b'\x1b[38;2;12;200;77m' + ('\u2588' * 12).encode() + b'\x1b[0m\r\n\x1b[1;3mHistorical glyphs\x1b[0m')
T.GLib.timeout_add(200, lambda: loop.quit())
loop.run()
image = T.Gdk.pixbuf_get_from_window(window.get_window(), 0, 0, window.get_allocated_width(), window.get_allocated_height())
pixels = image.get_pixels()
assert bytes((12, 200, 77)) in pixels, 'VTE true-colour text did not paint'
# The actual modern-VTE app must expose the profile and remember it on launch.
chrome = T.Gtk.CssProvider()
chrome.load_from_data(T.CSS.encode())
T.Gtk.StyleContext.add_provider_for_screen(T.Gdk.Screen.get_default(), chrome,
                                         T.Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
assert set(window.profile_items) == {"Default", "Desktop Theme"}
window.on_switch()
assert window.profile_items['Default'].get_active()
window.profile_items['Desktop Theme'].set_active(True)
assert screen.profile == app.profile == 'Desktop Theme'
assert T.Application([]).profile == 'Desktop Theme'
second = window.add_screen(['/bin/bash', '-c', 'sleep 20'], '/work')
window.on_switch()
assert second.profile == 'Desktop Theme'
window.profile_items['Default'].set_active(True)
window.notebook.set_current_page(0)
window.on_switch()
assert window.profile_items['Desktop Theme'].get_active()
assert app.profile == 'Default', 'switching tabs must not overwrite the saved preference'
window.close_screen(second)
# Test both palettes below the app CSS priority: historical chrome must not
# shadow the system palette used for terminal text and selection.
def painted_background(expected):
    T.GLib.timeout_add(150, lambda: loop.quit())
    loop.run()
    image = T.Gdk.pixbuf_get_from_window(window.get_window(), 0, 0,
                                       window.get_allocated_width(), window.get_allocated_height())
    value = bytes.fromhex(expected.lstrip('#'))
    assert image.get_pixels().count(value) > image.get_width() * image.get_height() / 2, expected

for foreground, background, accent in [('#e8e5de', '#282725', '#3366cc'),
                                        ('#222222', '#ffffff', '#22aa66')]:
    name = 'TestTheme' + background.lstrip('#')
    directory = Path.home() / '.themes' / name / 'gtk-3.0'
    directory.mkdir(parents=True)
    (directory / 'gtk.css').write_text('@define-color base_color %s;\n@define-color selected_bg_color %s;\n@define-color selected_fg_color #ffffff;\n@define-color text_color %s;\nentry { color: @text_color; }' % (background, accent, foreground))
    T.Gtk.Settings.get_default().set_property('gtk-theme-name', name)
    T.GLib.timeout_add(150, lambda: loop.quit())
    loop.run()
    actual_fg, actual_bg = app.theme_colors()
    assert actual_fg.equal(T.rgba(foreground)), actual_fg
    assert actual_bg.equal(T.rgba(background)), actual_bg
    painted_background(background)
    assert app.theme_entry.get_style_context().lookup_color('selected_bg_color')[1].equal(T.rgba(accent))
window.profile_items['Default'].set_active(True)
assert T.Application([]).profile == 'Default'
painted_background(T.BACKGROUND)
app.profile_path.write_text('{invalid json')
assert T.Application([]).profile == 'Default'
print('PASS: actual terminal profile menu, remembered selection, live light/dark colours and unchanged Default')
window.destroy()
print('PASS: original FreeType rasterizer, VTE true colour and clean child environment')
print('PASS: terminal GTK paste shortcuts, Unicode clipboard and shell-quoted URI drops')
PY
cat > "$run/inside.sh" <<'INNER'
set -euo pipefail
source /source/tools/lib/session-guard.sh
sg_require_offscreen
mkdir -p /work/home /tmp/.X11-unix
trap 'kill $(jobs -pr) 2>/dev/null || true; wait || true' EXIT
"$XVFB" :93 -screen 0 1024x768x24 -nolisten tcp -ac >/work/xvfb.log 2>&1 &
for _ in {1..100}; do test -S /tmp/.X11-unix/X93 && break; sleep .05; done
test -S /tmp/.X11-unix/X93
DISPLAY=:93 LD_PRELOAD="$TEST_PRELOAD" _UNITY_TERMINAL_PRELOAD= \
  FONTCONFIG_FILE="$TEST_FONTS" "$PYTHON" /work/check.py
INNER
"$BWRAP" --die-with-parent --new-session --unshare-all --ro-bind /nix /nix \
  --ro-bind "$repo" /source --bind "$run" /work --proc /proc --dev /dev \
  --tmpfs /tmp --symlink "$(dirname "$BASH")" /bin --clearenv \
  --setenv HOME /work/home --setenv QT_QPA_PLATFORM offscreen \
  --setenv PATH "$TEST_PATH" --setenv GI_TYPELIB_PATH "$GI_TYPELIB_PATH" \
  --setenv TEST_PRELOAD "$TEST_PRELOAD" --setenv TEST_FONTS "$TEST_FONTS" \
  --setenv PYTHON "$PYTHON" --setenv XVFB "$XVFB" --setenv LANG C.UTF-8 \
  "$BASH" /work/inside.sh
