"""Private-display compatibility and dependency checks for the original viewer."""
import ctypes
import importlib.util
import shlex
import json
import statistics
import os
from pathlib import Path
import subprocess
import sys
import time

assert os.environ.get("DISPLAY") == ":93"
assert os.environ.get("HOME") == "/home/test" and Path("/work/inside.sh").is_file()
config = json.loads((Path(sys.argv[1]) / "libexec/unity-quantal/config.json").read_text())
viewer = Path(sys.argv[2])
sys.dont_write_bytecode = True
module_dir = Path(sys.argv[1]) / 'libexec/unity-quantal'
sys.path.insert(0, str(module_dir))
spec = importlib.util.spec_from_file_location('viewer_launch', module_dir / 'viewer-launch.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
cache = (Path(config['runtime']) / 'usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders.cache').read_text().splitlines()
for index, line in enumerate(cache):
    parts = shlex.split(line)
    if len(parts) > 2 and parts[0] in ['pcx', 'wmf', 'wbmp', 'ras', 'ani', 'jpeg2000'] and parts[1].isdigit():
        assert all('.' + ext in launcher.LEGACY_SUFFIXES for ext in shlex.split(cache[index + 2]) if ext)
assert launcher.legacy_arguments(['--new-instance', 'file:///work/a%20b.PCX']) == (['file:///work/a%20b.PCX'], ['--new-instance'])
assert launcher.legacy_arguments(['--', '-sample.jpc']) == (['-sample.jpc'], [])
assert launcher.legacy_arguments(['--version', 'file.pcx']) is None
assert launcher.legacy_arguments(['file://[invalid']) is None
Path('/work/folder.pcx').mkdir()
assert launcher.legacy_arguments(['/work/folder.pcx']) is None
calls = []
original_exec, original_main = launcher.os.execv, launcher.isolated.main
class Executed(Exception): pass
def capture_exec(path, arguments):
    calls.append((path, arguments))
    raise Executed
try:
    launcher.os.execv = capture_exec
    launcher.isolated.main = lambda app, files, **options: calls.append((app, files, options))
    try:
        launcher.main(['--', '/work/name with spaces.png'])
    except Executed:
        pass
    assert calls[-1] == (config['viewer'], [config['viewer'], '--', '/work/name with spaces.png'])
    launcher.main(['-f', '/work/old.apm'])
    assert calls[-1] == ('eog', ['/work/old.apm'], {'viewer_flags': ['-f']})
finally:
    launcher.os.execv, launcher.isolated.main = original_exec, original_main
entry = (Path(sys.argv[1]) / 'share/applications/unity-original-eog.desktop').read_text()
assert 'Exec=' + str(Path(sys.argv[1]) / 'bin/unity-quantal-viewer') + ' -- %F' in entry
print('PASS: desktop routing, legacy extensions, flags, URIs and literal arguments', flush=True)
runtime = Path(config["runtime"])
Path("/work/fonts.conf").write_text(
    '<fontconfig><dir>' + str(runtime / "usr/share/fonts") + '</dir>'
    '<cachedir>/work/font-cache</cachedir></fontconfig>')
os.environ["FONTCONFIG_FILE"] = "/work/fonts.conf"
os.environ["XDG_DATA_DIRS"] = str(runtime / "usr/share")
library = Path("/work/images")
library.mkdir()
subprocess.run(["magick", "-size", "320x240", "xc:#da3020", str(library / "a.png")], check=True)
subprocess.run(["magick", "-size", "240x320", "xc:#20b050", str(library / "b.png")], check=True)


def call(*argv):
    return subprocess.check_output(argv, text=True, stderr=subprocess.DEVNULL).strip()


# Read pixels only from this private display; a mapped window is not proof of paint.
x = ctypes.CDLL(config["libX11"])
x.XOpenDisplay.argtypes = [ctypes.c_char_p]
x.XOpenDisplay.restype = ctypes.c_void_p
x.XGetImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                       ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
x.XGetImage.restype = ctypes.c_void_p
x.XGetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
x.XGetPixel.restype = ctypes.c_ulong
x.XDestroyImage.argtypes = [ctypes.c_void_p]
display = x.XOpenDisplay(b":93")
assert display


def painted(window):
    pixels = x.XGetImage(display, int(window), 200, 200, 1, 1, 0xffffffff, 2)
    assert pixels
    pixel = x.XGetPixel(pixels, 0, 0)
    x.XDestroyImage(pixels)
    red, green, blue = (pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255
    return red > 160 and green < 100 and blue < 100


def launch(mode, image, arguments=None, cwd=None):
    env = os.environ.copy()
    if mode in ("original", "original-fonts"):
        env.update(LD_LIBRARY_PATH=config["modernLibraries"] + ":/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:/usr/lib",
                   GSETTINGS_SCHEMA_DIR="/usr/share/glib-2.0/schemas", GSETTINGS_BACKEND="memory",
                   GDK_PIXBUF_MODULE_FILE="/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders.cache",
                   GTK_MODULES="", GIO_USE_VFS="local", GIO_EXTRA_MODULES="", GIO_MODULE_DIR="/nonexistent", UBUNTU_MENUPROXY="0")
        env.pop("FONTCONFIG_FILE", None)
        env.pop("FONTCONFIG_PATH", None)
        argv = [config["bwrap"], "--bind", "/", "/"]
        for name in ["usr", "lib", "lib64", "etc"]:
            argv += ["--ro-bind", str(runtime / name), "/" + name]
        for name in ["passwd", "group", "machine-id"]:
            argv += ["--ro-bind", "/work/" + name, "/etc/" + name]
        argv += [config["loader"], "/usr/bin/eog"]
    elif mode == "isolated":
        notice = Path.home() / '.local/state/unity-quantal/isolated/eog-workflow-v1'
        notice.parent.mkdir(parents=True, exist_ok=True)
        notice.touch()
        argv = [str(Path(sys.argv[1]) / "bin/unity-quantal-isolated"), "eog", "--"]
    elif mode == "session":
        argv = [str(Path(sys.argv[1]) / "bin/unity-quantal-viewer")]
    elif mode == "runtime":
        argv = [str(Path(sys.argv[1]) / "bin/unity-quantal-runtime"), "/usr/bin/eog"]
    elif mode == "direct":
        env = direct_environment.copy()
        argv = [str(viewer / "libexec/eog")]
    else:
        argv = [str(viewer / "bin/unity-image-viewer")]
    if mode in ('original-fonts', 'native-fonts'):
        env.pop('FONTCONFIG_FILE', None)
    if mode == 'modern' and os.environ.get('VIEWER_GDB'):
        argv = [os.environ['VIEWER_GDB'], '-batch', '-ex', 'set pagination off',
                '-ex', 'run', '-ex', 'thread apply all bt', '--args', '/bin/bash', *argv]
    log = open("/work/" + mode + ".log", "w")
    started = time.monotonic()
    process = subprocess.Popen([*argv, *([] if mode == "isolated" else ["--new-instance"]), *(arguments if arguments is not None else [str(image)])], env=env, cwd=cwd, stdout=log, stderr=log)
    log.close()
    configured = set()
    for _ in range(1200):
        if process.poll() is not None:
            raise AssertionError(f"{mode} exited {process.returncode}: " + Path(log.name).read_text())
        # bwrap's child owns the baseline window, so match class in this empty server.
        result = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "^Eog$"], capture_output=True, text=True)
        if result.returncode == 0:
            for window in result.stdout.splitlines():
                if mode == 'isolated' and window not in configured:
                    # Without an outer WM, Xpra waits for the client window's
                    # configure event. Supply it on this private server only.
                    subprocess.run(['xdotool', 'windowsize', window, '800', '600'], check=True)
                    configured.add(window)
                if image.name in call("xdotool", "getwindowname", window) and painted(window):
                    return process, window, time.monotonic() - started
        time.sleep(.025)
    Path("/work/" + mode + "-tree.txt").write_text(call("xwininfo", "-root", "-tree"))
    raise AssertionError(f"No {mode} window: " + Path(log.name).read_text())


def close(process, window):
    subprocess.run(["xdotool", "windowfocus", window, "key", "ctrl+q"], check=True)
    try:
        process.wait(20)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(5)
        raise AssertionError("Viewer did not close normally")
    assert process.returncode == 0, process.returncode


for mode in ["original", "modern"]:
    process, window, elapsed = launch(mode, library / "a.png")
    try:
        subprocess.run(["xdotool", "windowsize", window, "800", "600", "windowfocus", window], check=True)
        time.sleep(.6)
        subprocess.run(["magick", "import", "-window", window, "/work/" + mode + ".png"], check=True)
        assert "a.png" in call("xdotool", "getwindowname", window)
        subprocess.run(["xdotool", "key", "Right"], check=True)
        time.sleep(.3)
        assert "b.png" in call("xdotool", "getwindowname", window)
        subprocess.run(["xdotool", "key", "Left"], check=True)
        time.sleep(.3)
        assert "a.png" in call("xdotool", "getwindowname", window)
        if mode == 'modern':
            subprocess.run(['xdotool', 'windowfocus', window, 'key', 'ctrl+c'], check=True)
        for shortcut, title in [("alt+Return", "Image Properties"), ("ctrl+shift+s", "Save Image"), ("ctrl+p", "Print")]:
            subprocess.run(["xdotool", "windowfocus", window, "key", shortcut], check=True)
            for _ in range(100):
                result = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "^" + title + "$"], capture_output=True, text=True)
                if result.returncode == 0:
                    dialog = result.stdout.splitlines()[-1]
                    break
                time.sleep(.05)
            else:
                raise AssertionError(f"{mode}: no {title} dialog")
            subprocess.run(["magick", "import", "-window", dialog, "/work/" + mode + "-" + title.replace(' ', '-') + ".png"], check=True)
            subprocess.run(["xdotool", "windowfocus", dialog, "key", "Escape"], check=True)
            time.sleep(.1)
        pid = int(call("xprop", "-id", window, "_NET_WM_PID").split("=")[-1])
        maps = Path(f"/proc/{pid}/maps").read_text()
        Path("/work/" + mode + "-maps.txt").write_text(maps)
        if mode == "modern":
            direct_environment = dict(part.decode().split('=', 1) for part in Path(f"/proc/{pid}/environ").read_bytes().split(b'\0') if part)
            Path('/work/viewer-env.json').write_text(json.dumps(direct_environment))
            icon_probe = """
import ctypes as c, os, json
os.environ.update(json.load(open('/work/viewer-env.json')))
gtk=c.CDLL(LIBRARY)
gtk.gtk_init(None,None)
gtk.gdk_atom_intern.argtypes=[c.c_char_p,c.c_int]; gtk.gdk_atom_intern.restype=c.c_void_p
gtk.gtk_clipboard_get.argtypes=[c.c_void_p]; gtk.gtk_clipboard_get.restype=c.c_void_p
gtk.gtk_clipboard_wait_for_image.argtypes=[c.c_void_p]; gtk.gtk_clipboard_wait_for_image.restype=c.c_void_p
gtk.gdk_pixbuf_get_width.argtypes=[c.c_void_p]
pixbuf=gtk.gtk_clipboard_wait_for_image(gtk.gtk_clipboard_get(gtk.gdk_atom_intern(b'CLIPBOARD',0)))
assert pixbuf and gtk.gdk_pixbuf_get_width(pixbuf)==320, 'native clipboard image'
gtk.gtk_icon_theme_get_default.restype=c.c_void_p
gtk.gtk_icon_theme_load_icon.argtypes=[c.c_void_p,c.c_char_p,c.c_int,c.c_int,c.POINTER(c.c_void_p)]
gtk.gtk_icon_theme_load_icon.restype=c.c_void_p
class Error(c.Structure): _fields_=[('domain',c.c_uint),('code',c.c_int),('message',c.c_char_p)]
for name in [b'go-previous',b'object-rotate-left',b'image-loading']:
    error=c.c_void_p()
    result=gtk.gtk_icon_theme_load_icon(gtk.gtk_icon_theme_get_default(),name,24,0,c.byref(error))
    assert result, (name, c.cast(error,c.POINTER(Error)).contents.message if error.value else '')
""".replace('LIBRARY', repr(next(line.split()[-1] for line in maps.splitlines() if 'unity-viewer-widget-abi/lib/libgtk-3.so' in line)))
            subprocess.run([sys.executable, '-c', icon_probe], check=True)
            assert "unity-viewer-widget-abi/lib/libgdk-3" in maps
            assert "unity-viewer-widget-abi/lib/libgtk-3" in maps
            for name in ["libpango-1.0", "libpangocairo", "libfreetype", "libfontconfig", "libcairo.so"]:
                entries = [line for line in maps.splitlines() if name in line]
                assert entries and all('unity-historical-text' in line for line in entries), entries
            for name in ["libgdk_pixbuf", "libexif", "liblcms2", "libexempi", "librsvg", "libjpeg"]:
                entries = [line for line in maps.splitlines() if name in line]
                assert entries, name
                assert all(str(runtime) not in line and "/usr/lib/" not in line for line in entries), entries
        print(f"PASS {mode}: selected image, navigation and properties/save/print dialogs; first paint in {elapsed:.3f}s", flush=True)
    finally:
        close(process, window)

# Compare text independently from intentional corrections in image colour decoding.
for geometry in ['800x25+0+0', '800x24+0+61']:
    difference = call('magick', '/work/original.png', '-crop', geometry, '+repage',
                      '(', '/work/modern.png', '-crop', geometry, '+repage', ')',
                      '-compose', 'difference', '-composite', '-format', '%[fx:mean]', 'info:')
    assert float(difference) == 0, (geometry, difference)
print('PASS: historical menu and toolbar text match pixel for pixel', flush=True)

for mode in ['session', 'runtime']:
    process, window, elapsed = launch(mode, library / 'a.png')
    close(process, window)
    print(f'PASS {mode}: native launch and normal exit ({elapsed:.3f}s)', flush=True)

for mode in ['original-fonts', 'native-fonts']:
    process, window, elapsed = launch(mode, library / 'a.png')
    subprocess.run(['xdotool', 'windowsize', window, '800', '600'], check=True)
    time.sleep(.3)
    subprocess.run(['magick', 'import', '-window', window, '/work/' + mode + '.png'], check=True)
    close(process, window)
difference = call('magick', '/work/original-fonts.png', '-crop', '800x25+0+0', '+repage',
                  '(', '/work/native-fonts.png', '-crop', '800x25+0+0', '+repage', ')',
                  '-compose', 'difference', '-composite', '-format', '%[fx:mean]', 'info:')
assert float(difference) == 0, difference
print('PASS: historical text with the default font configuration', flush=True)

# Paths and image sizes exercise the installed launcher, not just the binary.
process, window, elapsed = launch('session', library / 'a.png', [str(library)])
close(process, window)
other = Path('/work/other'); other.mkdir()
spaced = other / 'name with spaces.png'
spaced.write_bytes((library / 'a.png').read_bytes())
for values in [[spaced.as_uri()], [str(library / 'a.png'), str(spaced)]]:
    process, window, elapsed = launch('session', spaced if len(values) == 1 else library / 'a.png', values)
    if len(values) > 1:
        subprocess.run(['xdotool', 'windowfocus', window, 'key', 'Right'], check=True)
        time.sleep(.2)
        assert spaced.name in call('xdotool', 'getwindowname', window)
    close(process, window)
leading = library / '-leading.png'
leading.write_bytes((library / 'a.png').read_bytes())
process, window, elapsed = launch('session', leading, ['--', leading.name], str(library))
close(process, window)
svg = library / 'vector.svg'
svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240"><rect width="320" height="240" fill="#da3020"/></svg>')
process, window, elapsed = launch('session', svg)
subprocess.run(['xdotool', 'windowfocus', window, 'key', 'plus', 'minus'], check=True)
close(process, window)
for document in [library / 'a.png', svg]:
    output = Path('/work') / (document.stem + '.pdf')
    settings = Path.home() / '.config/eog/eog-print-settings.ini'
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text('[Print Settings]\nprinter=Print to File\noutput-uri=' + output.as_uri() + '\noutput-file-format=pdf\n')
    process, window, elapsed = launch('session', document)
    subprocess.run(['xdotool', 'windowfocus', window, 'key', 'ctrl+p'], check=True)
    for _ in range(100):
        result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '^Print$'], capture_output=True, text=True)
        if result.returncode == 0:
            dialog = result.stdout.splitlines()[-1]
            break
        time.sleep(.05)
    else:
        raise AssertionError('No print-to-file dialog')
    time.sleep(.3)
    subprocess.run(['xdotool', 'windowfocus', dialog, 'key', 'alt+p'], check=True)
    for _ in range(100):
        if output.exists() and b'%%EOF' in output.read_bytes():
            break
        time.sleep(.05)
    assert output.exists(), 'Print to File did not create ' + str(output)
    pdf = output.read_bytes()
    assert pdf.startswith(b'%PDF') and b'/Subtype /Image' in pdf and len(pdf) > 1000
    close(process, window)
print('PASS: PNG and SVG print to PDF', flush=True)
large = library / 'large.png'
subprocess.run(['magick', '-size', '8192x4096', 'xc:#da3020', str(large)], check=True)
process, window, elapsed = launch('session', large)
close(process, window)
print(f'PASS: directory, URI, multiple folders, leading dash, SVG zoom; 32 MP image in {elapsed:.3f}s', flush=True)
many = Path('/work/many'); many.mkdir()
for index in range(1000):
    os.link(library / 'a.png', many / f'{index:04}.png')
process, window, elapsed = launch('session', many / '0000.png')
close(process, window)
print(f'PASS: directory of 1,000 images in {elapsed:.3f}s', flush=True)

if os.environ.get("VIEWER_BENCHMARK") == "1":
    samples = {}
    modes = ["session", "modern", "direct"]
    if os.environ.get('VIEWER_COMPARE_ISOLATED') == '1':
        modes.append('isolated')
    for mode in modes:
        samples[mode] = []
        for _ in range(20):
            process, window, elapsed = launch(mode, library / "a.png")
            samples[mode].append(elapsed)
            close(process, window)
        ordered = sorted(samples[mode])
        print(f"TIMING {mode}: median={statistics.median(ordered):.3f}s p95={ordered[18]:.3f}s n=20", flush=True)
        Path('/work/timings.json').write_text(json.dumps(samples, indent=2))
    assert sorted(samples['session'])[18] < 1
    if 'isolated' in samples:
        assert statistics.median(samples['session']) < statistics.median(samples['isolated']) / 2
    assert statistics.median(samples['session']) - statistics.median(samples['direct']) < .1
