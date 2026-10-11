"""Private-display compatibility and dependency checks for the original viewer."""
import ctypes
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


def launch(mode, image):
    env = os.environ.copy()
    if mode == "original":
        env.update(LD_LIBRARY_PATH=config["modernLibraries"] + ":/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:/usr/lib",
                   GSETTINGS_SCHEMA_DIR="/usr/share/glib-2.0/schemas", GSETTINGS_BACKEND="memory",
                   GDK_PIXBUF_MODULE_FILE="/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders.cache",
                   GTK_MODULES="", GIO_USE_VFS="local", GIO_EXTRA_MODULES="", GIO_MODULE_DIR="/nonexistent", UBUNTU_MENUPROXY="0")
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
    elif mode == "direct":
        env = direct_environment.copy()
        argv = [str(viewer / "libexec/eog")]
    else:
        argv = [str(viewer / "bin/unity-image-viewer")]
    log = open("/work/" + mode + ".log", "w")
    started = time.monotonic()
    process = subprocess.Popen([*argv, *([] if mode == "isolated" else ["--new-instance"]), str(image)], env=env, stdout=log, stderr=log)
    log.close()
    for _ in range(1200):
        if process.poll() is not None:
            raise AssertionError(f"{mode} exited {process.returncode}: " + Path(log.name).read_text())
        # bwrap's child owns the baseline window, so match class in this empty server.
        result = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "^Eog$"], capture_output=True, text=True)
        if result.returncode == 0:
            for window in result.stdout.splitlines():
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
            assert "unity-viewer-widget-abi/lib/libgdk-3" in maps
            assert "unity-viewer-widget-abi/lib/libgtk-3" in maps
            for name in ["libgdk_pixbuf", "libexif", "liblcms2", "libexempi", "librsvg", "libjpeg"]:
                entries = [line for line in maps.splitlines() if name in line]
                assert entries, name
                assert all(str(runtime) not in line and "/usr/lib/" not in line for line in entries), entries
        print(f"PASS {mode}: selected image, navigation and properties/save/print dialogs; first paint in {elapsed:.3f}s", flush=True)
    finally:
        close(process, window)

if os.environ.get("VIEWER_BENCHMARK") == "1":
    samples = {}
    for mode in ["modern", "direct", "isolated"]:
        samples[mode] = []
        for _ in range(20):
            process, window, elapsed = launch(mode, library / "a.png")
            samples[mode].append(elapsed)
            close(process, window)
        ordered = sorted(samples[mode])
        print(f"TIMING {mode}: median={statistics.median(ordered):.3f}s p95={ordered[18]:.3f}s n=20", flush=True)
        Path('/work/timings.json').write_text(json.dumps(samples, indent=2))
    assert sorted(samples['modern'])[18] < 1
    assert statistics.median(samples['modern']) < statistics.median(samples['isolated']) / 2
    assert statistics.median(samples['modern']) - statistics.median(samples['direct']) < .1
