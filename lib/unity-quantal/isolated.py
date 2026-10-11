"""Private X11 application sessions and explicit document import/export."""

import argparse
import configparser
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text())
APPS = {"gedit": "Text Editor", "eog": "Image Viewer", "file-roller": "Archive Manager", "gcalctool": "Calculator",
        "rhythmbox": "Rhythmbox"}
# Rhythmbox keeps a private profile, reads the music library, and plays
# through the host's PulseAudio socket; it imports and exports no files.
MEDIA = {"rhythmbox"}
MIMES = {
    "gedit": ["text/plain", "text/x-python", "text/x-nix", "text/x-lua", "text/x-c",
              "text/x-c++src", "text/x-c++hdr", "text/x-chdr", "text/x-csrc", "text/x-shellscript",
              "application/json", "application/x-shellscript", "text/x-qml", "text/x-diff",
              "text/x-patch", "text/csv", "application/xml", "text/xml"],
    "eog": ["image/png", "image/jpeg", "image/gif", "image/bmp", "image/tiff", "image/x-icon",
            "image/svg+xml", "image/svg+xml-compressed", "image/x-pcx", "image/x-wmf", "image/wmf",
            "image/vnd.wap.wbmp", "image/x-sun-raster", "image/x-cmu-raster", "application/x-navi-animation",
            "image/jp2", "image/jpeg2000", "image/jpx",
            "image/x-portable-anymap", "image/x-portable-bitmap", "image/x-portable-graymap",
            "image/x-portable-pixmap", "image/x-xbitmap", "image/x-xpixmap", "image/x-tga", "image/icns"],
    "file-roller": ["application/zip", "application/x-tar", "application/x-compressed-tar",
                    "application/x-bzip-compressed-tar", "application/x-xz-compressed-tar"],
    "gcalctool": [],
    "rhythmbox": [],
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".ico", ".svg", ".svgz",
                  ".pcx", ".wmf", ".apm", ".wbmp", ".ras", ".sun", ".ani", ".jp2", ".jpc", ".j2k", ".jpf", ".jpx",
                  ".icns", ".pnm", ".pbm", ".pgm", ".ppm", ".qtif", ".xpm", ".tga", ".xbm"}
LIMIT = 512 * 1024 * 1024
FEATURES = [
    "--clipboard=no", "--notifications=no", "--system-tray=no", "--bell=no",
    "--webcam=no", "--audio=no", "--speaker=disabled", "--microphone=disabled",
    "--file-transfer=no", "--printing=no", "--open-files=no", "--open-url=no",
    "--dbus=no", "--dbus-control=no", "--mmap=no", "--video=no",
    "--encodings=rgb24,rgb32", "--compressors=none", "--compression_level=0",
    "--remote-logging=no", "--xsettings=no", "--sharing=no", "--lock=yes",
    "--opengl=no", "--tray=no", "--splash=no", "--headerbar=no",
]


def install_desktops(package):
    destination = package / "share/applications"
    destination.mkdir(parents=True, exist_ok=True)
    root = Path(CONFIG["runtime"])
    for app, label in APPS.items():
        source = configparser.ConfigParser(interpolation=None, strict=False)
        source.read(root / "usr/share/applications" / (app + ".desktop"))
        icon = source["Desktop Entry"].get("Icon", app)
        icons = sorted((root / "usr/share/icons").rglob(icon + ".png"))
        if icons:
            icon = str(next((p for p in icons if "48x48" in p.parts or "48" in p.parts), icons[0]))
        entry = configparser.ConfigParser(interpolation=None)
        entry.optionxform = str
        entry["Desktop Entry"] = {
            "Type": "Application", "Name": label + " (Ubuntu 12.10)", "Icon": icon,
            "Exec": (str(package / "bin/unity-quantal-viewer") + " -- %F") if app == "eog" else
                    str(package / "bin/unity-quantal-isolated") + " " + app + ("" if app in MEDIA else " -- %F"),
            "OnlyShowIn": "Unity;", "Terminal": "false", "StartupNotify": "false",
            "StartupWMClass": app, "Categories": "AudioVideo;Audio;Player;" if app in MEDIA else "Utility;",
            "MimeType": ";".join(MIMES[app]) + ";",
        }
        with (destination / ("unity-original-" + app + ".desktop")).open("w") as stream:
            entry.write(stream, space_around_delimiters=False)


def install_defaults(state):
    def update(path, fallback=None, legacy=False):
        data = configparser.ConfigParser(interpolation=None, strict=False)
        data.optionxform = str
        if fallback:
            data.read(fallback)
        data.read(path)
        if "Default Applications" not in data:
            data["Default Applications"] = {}
        for app, types in MIMES.items():
            for mime in types:
                data["Default Applications"][mime] = "unity-original-" + app + ".desktop;"
        if legacy:
            # GLib 2.34 reads a single string, including any trailing semicolon.
            for mime, value in data["Default Applications"].items():
                data["Default Applications"][mime] = value.split(";")[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with temporary.open("w") as stream:
            data.write(stream, space_around_delimiters=False)
        temporary.replace(path)
    config = Path(state["config_home"])
    update(config / "unity-mimeapps.list")
    # GLib 2.34 predates desktop-specific configuration precedence. Only the
    # legacy runtime sees this XDG_DATA_HOME; native desktops keep their own.
    update(Path(state["data_home"]) / "unity-quantal-session/applications/mimeapps.list",
           config / "mimeapps.list", legacy=True)


def dialog(*args):
    result = subprocess.run([CONFIG["zenity"], *args], text=True, capture_output=True)
    if result.returncode == 1:
        return None
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "File dialog failed")
    return result.stdout.rstrip("\n")


def local_file(value):
    if value.startswith("file:"):
        uri = urlsplit(value)
        if uri.netloc not in ("", "localhost"):
            raise ValueError("Only local files can be opened")
        value = unquote(uri.path)
    elif "://" in value:
        raise ValueError("Only local files can be opened")
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError("Choose a regular file smaller than 512 MiB")
    return path


def image_inputs(files):
    """Let EOG enumerate neighboring images, without granting directory access."""
    if len(files) != 1:
        return files
    selected = files[0]
    siblings = []
    with os.scandir(selected.parent) as entries:
        for entry in entries:
            if Path(entry.name).suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if entry.is_file(follow_symlinks=False) and entry.stat(follow_symlinks=False).st_size <= LIMIT:
                siblings.append(Path(entry.path))
    return [selected] + sorted((p for p in siblings if p != selected), key=lambda p: p.name)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def regular_files(directory):
    """Read output only after the entire sandbox has stopped; reject links."""
    result = []
    for parent, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs + files:
            path = Path(parent) / name
            mode = path.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)) or path.is_symlink():
                raise ValueError("Export refused: output contains a link or special file")
            if len(path.relative_to(directory).parts) > 32:
                raise ValueError("Export refused: folders are nested too deeply")
        result.extend(Path(parent) / name for name in files)
        if len(result) > 10000:
            raise ValueError("Export refused: more than 10,000 files")
    return sorted(result)


def copy_regular(source, destination):
    # No symlinks, devices, FIFOs or executable/set-ID permission propagation.
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
            raise ValueError("Export refused: invalid or oversized file")
        with os.fdopen(fd, "rb", closefd=False) as incoming:
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as outgoing:
                temporary = Path(outgoing.name)
                try:
                    shutil.copyfileobj(incoming, outgoing)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                    os.chmod(temporary, 0o600)
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
    finally:
        os.close(fd)


def media_paths():
    """Host paths a media application may use: its profile, library, and sound server."""
    base = Path.home() / ".local/state/unity-quantal/isolated"
    pulse = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())) / "pulse/native"
    return base / "rhythmbox-profile", Path(CONFIG["musicLibrary"]), pulse


def base_namespace(run, client=False, app=None):
    command = [CONFIG["bwrap"], "--die-with-parent", "--new-session", "--unshare-all", "--unshare-user",
               "--disable-userns", "--cap-drop", "ALL", "--tmpfs", "/",
               "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run", "--perms", "1777", "--dir", "/tmp/.X11-unix"]
    for path in Path(CONFIG["isolatedClosure"]).read_text().splitlines():
        command += ["--ro-bind", path, path]
    root = Path(CONFIG["runtime"])
    for name in ["bin", "sbin", "usr", "lib", "lib64", "etc", "var"]:
        if (root / name).exists():
            command += ["--ro-bind", str(root / name), "/" + name]
    command += ["--ro-bind", CONFIG["legacyGtkModule"],
                "/usr/lib/x86_64-linux-gnu/gtk-3.0/modules/libcanberra-gtk3-module.so"]
    loader = root / "lib64/ld-linux-x86-64.so.2"
    target = os.readlink(loader) if loader.is_symlink() else "/lib64/ld-linux-x86-64.so.2"
    command += ["--ro-bind", CONFIG["loader"], target,
                "--ro-bind", str(run / "passwd"), "/etc/passwd",
                "--ro-bind", str(run / "group"), "/etc/group",
                "--ro-bind", str(run / "machine-id"), "/etc/machine-id",
                "--ro-bind", str(run / "machine-id"), "/var/lib/dbus/machine-id",
                "--bind", str(run / "transport"), "/transport",
                "--perms", "0700", "--dir", "/run/user/1000", "--tmpfs", "/home/legacy"]
    environment = {
        "HOME": "/home/legacy", "USER": "legacy", "LOGNAME": "legacy",
        "PATH": str(Path(CONFIG["xpra"]).parent) + ":" + str(Path(CONFIG["bash"]).parent) + ":/usr/bin:/bin",
        "XDG_RUNTIME_DIR": "/run/user/1000", "LANG": "C.UTF-8",
        "NO_AT_BRIDGE": "1", "GTK_A11Y": "none", "GDK_BACKEND": "x11",
        "XPRA_SKIP_UI": "1", "XPRA_LOG_DIR": "/tmp", "XPRA_SOCKET_DIR": "/transport",
        "XPRA_SOCKET_DIRS": "/transport", "XPRA_SYSTEM_CONF_DIRS": "/nonexistent",
        "XPRA_USER_CONF_DIRS": "/nonexistent", "XPRA_DEFAULT_CONF_DIRS": "/nonexistent",
        "XPRA_FULL_INFO": "0", "XPRA_REMOTE_LOGGING": "0", "XPRA_X11_PROPERTIES_DEBUG": "",
    }
    if client:
        display = os.environ.get("DISPLAY", "")
        if not display.startswith(":") or not display[1:].split(".")[0].isdigit():
            raise RuntimeError("A local X11 display is required")
        number = display[1:].split(".")[0]
        sock = "/tmp/.X11-unix/X" + number
        command += ["--ro-bind", sock, sock]
        environment["DISPLAY"] = display
        authority = os.environ.get("XAUTHORITY")
        if authority:
            command += ["--ro-bind", authority, "/run/Xauthority"]
            environment["XAUTHORITY"] = "/run/Xauthority"
    else:
        # Xpra 6.5.3 imports MmapPointerError even with mmap disabled. Its
        # import blocker breaks window forwarding; protocol features stay off.
        environment["XPRA_ENFORCE_FEATURES"] = "0"
        if app in MEDIA:
            profile, library, pulse = media_paths()
            # The library is read-only: 2.97 keeps ratings and play counts in its own database.
            command += ["--bind", str(profile), "/home/legacy", "--dir", "/home/legacy/Music",
                        "--ro-bind-try", str(library), "/home/legacy/Music"]
        else:
            command += ["--ro-bind", str(run / "input"), "/home/legacy/Input",
                        "--bind", str(run / "output"), "/home/legacy/Documents"]
        # All original GTK apps need the event backend, not just Rhythmbox.
        # Share only this socket, never the host session bus or sound devices.
        pulse = media_paths()[2]
        if pulse.is_socket():
            command += ["--ro-bind", str(pulse), "/run/user/1000/pulse/native"]
        if app == "eog" and (run / "images.json").is_file():
            # Read-only file mounts avoid copying and hashing full-size images
            # before the first window appears. Unrelated files stay hidden.
            for source, name in json.loads((run / "images.json").read_text()):
                command += ["--ro-bind", source, "/home/legacy/Input/" + name]
        command += ["--ro-bind", str(HERE / "isolated.py"), "/runner/isolated.py",
                    "--ro-bind", str(HERE / "config.json"), "/runner/config.json"]
    command += ["--clearenv"]
    for key, value in environment.items():
        command += ["--setenv", key, value]
    command += ["--chdir", "/home/legacy", CONFIG["restrict"]]
    return command


def limits():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT, LIMIT))
    resource.setrlimit(resource.RLIMIT_NOFILE, (512, 512))


def worker(app, files):
    theme_file = Path("/transport/theme")
    theme = theme_name(theme_file.read_text()) if theme_file.is_file() else CONFIG["gtkTheme"]
    # Xpra's wrapper exports current typelibs, which break the 2012 PyGObject.
    os.environ.pop("GI_TYPELIB_PATH", None)
    environment = os.environ.copy()
    environment.update({
        "LD_LIBRARY_PATH": CONFIG["modernLibraries"] + ":/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:/usr/lib",
        "GSETTINGS_SCHEMA_DIR": "/usr/share/glib-2.0/schemas",
        "GDK_PIXBUF_MODULE_FILE": "/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders.cache",
        "UBUNTU_MENUPROXY": "0", "GIO_USE_VFS": "local",
        "GIO_EXTRA_MODULES": "", "GIO_MODULE_DIR": "/nonexistent", "GSETTINGS_BACKEND": "memory",
        "GTK_MODULES": "canberra-gtk-module", "GTK_IM_MODULE": "gtk-im-context-simple",
        "CANBERRA_DRIVER": "pulse", "PULSE_SERVER": "unix:/run/user/1000/pulse/native",
        "PATH": CONFIG["archivePath"] + ":/usr/bin:/bin", "XDG_DATA_DIRS": "/usr/share",
    })
    settings = Path.home() / ".config/gtk-3.0/settings.ini"
    settings.parent.mkdir(parents=True, exist_ok=True)
    sound_file = Path("/transport/sounds")
    sounds = json.loads(sound_file.read_text()) if sound_file.exists() else {
        "theme-name": "ubuntu", "event-sounds": True, "input-feedback-sounds": True}
    text_file = Path("/transport/text-settings")
    text = font_settings(json.loads(text_file.read_text()) if text_file.exists() else {})
    # GDK 3.6's X resource defaults take precedence over settings.ini for some
    # Xft properties. Set both on this worker's private X server.
    resources = "".join("Xft." + key.removeprefix("gtk-xft-") + ": "
                        + str(value / 1024 if key == "gtk-xft-dpi" else value) + "\n"
                        for key, value in text.items())
    resources += "Xft.autohint: 0\nXft.lcdfilter: lcddefault\n"
    xenv = {key: os.environ[key] for key in ("DISPLAY", "XAUTHORITY") if key in os.environ}
    if xenv.get("DISPLAY"):
        subprocess.run([CONFIG["xrdb"], "-nocpp", "-merge"], input=resources, text=True, env=xenv, check=True)
    settings.write_text("[Settings]\ngtk-theme-name=" + theme + "\ngtk-icon-theme-name=ubuntu-mono-dark\ngtk-font-name=Ubuntu 11\n"
                        + "".join(key + "=" + str(value) + "\n" for key, value in text.items())
                        + "gtk-sound-theme-name=" + sounds["theme-name"] + "\n"
                        "gtk-enable-event-sounds=" + str(int(sounds["event-sounds"])) + "\n"
                        "gtk-enable-input-feedback-sounds=" + str(int(sounds["input-feedback-sounds"])) + "\n")
    if app in MEDIA:
        environment.update({"GSETTINGS_BACKEND": "dconf", "GSETTINGS_SCHEMA_DIR": CONFIG["mediaSchemas"],
                            "PULSE_SERVER": "unix:/run/user/1000/pulse/native"})
        (Path.home() / ".config/user-dirs.dirs").write_text('XDG_MUSIC_DIR="$HOME/Music"\n')
    else:
        (Path.home() / ".config/user-dirs.dirs").write_text('XDG_DOCUMENTS_DIR="$HOME/Documents"\nXDG_DOWNLOAD_DIR="$HOME/Documents"\nXDG_PICTURES_DIR="$HOME/Documents"\n')
        os.chdir("/home/legacy/Documents")
    bus_config = Path.home() / "bus.conf"
    services = ""
    if app in MEDIA:
        # Only the settings service activates; its database stays in the profile.
        Path("/tmp/services").mkdir()
        Path("/tmp/services/ca.desrt.dconf.service").write_text(
            "[D-BUS Service]\nName=ca.desrt.dconf\nExec=/usr/bin/env LD_LIBRARY_PATH="
            + environment["LD_LIBRARY_PATH"] + " /usr/lib/dconf/dconf-service\n")
        services = "<servicedir>/tmp/services</servicedir>"
    bus_config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen><auth>EXTERNAL</auth>' + services + '<policy context="default"><allow send_destination="*"/><allow receive_sender="*"/><allow own="*"/></policy></busconfig>')
    argv = [CONFIG["isolatedArchive"] if app == "file-roller" else "/usr/bin/" + app]
    if app == "gedit":
        argv += ["--standalone"]
    elif app == "file-roller":
        argv += ["--default-dir=/home/legacy/Documents"]
    argv += files
    # Private D-Bus, with no host bus or host activation service directories.
    command = [str(Path(CONFIG["dbus"]).with_name("dbus-run-session")), "--dbus-daemon=" + CONFIG["dbus"], "--config-file=" + str(bus_config), "--", "/usr/bin/env"]
    command += [key + "=" + value for key, value in environment.items()]
    command += argv
    clean = os.environ.copy()
    clean.pop("DBUS_SESSION_BUS_ADDRESS", None)
    result = subprocess.call(command, env=clean)
    Path("/transport/exit-status").write_text(str(result))
    raise SystemExit(result)


def theme_name(value):
    # Private displays have no XSETTINGS; pass the chosen theme by name only.
    value = value.strip().strip("'")
    if value and "/" not in value and not value.startswith(".") \
            and (Path(CONFIG["runtime"]) / "usr/share/themes" / value / "gtk-3.0").is_dir():
        return value
    return CONFIG["gtkTheme"]


def current_theme():
    try:
        result = subprocess.run([str(HERE.parent.parent / "bin/unity-quantal-runtime"), "/usr/bin/gsettings", "get",
                                 "org.gnome.desktop.interface", "gtk-theme"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return CONFIG["gtkTheme"]
    return theme_name(result.stdout)


def font_settings(preferences):
    # Xpra does not forward XSETTINGS. Without explicit values GTK falls back
    # to different hinting and grayscale AA despite using the original libs.
    antialias = preferences.get("antialiasing", "rgba")
    hint = preferences.get("hinting", "slight")
    order = preferences.get("rgba-order", "rgb")
    return {
        "gtk-xft-antialias": int(antialias != "none"),
        "gtk-xft-hinting": int(hint != "none"),
        "gtk-xft-hintstyle": "hint" + (hint if hint in {"none", "slight", "medium", "full"} else "slight"),
        "gtk-xft-rgba": order if antialias == "rgba" and order in {"rgb", "bgr", "vrgb", "vbgr"} else "none",
        "gtk-xft-dpi": 96 * 1024,
    }


def current_font_preferences():
    environment = os.environ.copy()
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "GSETTINGS_BACKEND"):
        environment.pop(key, None)
    environment.update(GSETTINGS_SCHEMA_DIR=CONFIG["runtime"] + "/usr/share/glib-2.0/schemas",
                       DCONF_PROFILE=str(HERE / "dconf-profile"))
    try:
        result = subprocess.run([CONFIG["gsettings"], "list-recursively",
                                 "org.gnome.settings-daemon.plugins.xsettings"],
                                env=environment, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return {parts[1]: parts[2].strip("'") for line in result.stdout.splitlines()
                    if len(parts := line.split(maxsplit=2)) == 3
                    and parts[1] in {"antialiasing", "hinting", "rgba-order"}}
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {}


def run_session(run, app, files, *, attach=True):
    for name in ["input", "output", "transport"]:
        (run / name).mkdir(mode=0o700, exist_ok=True)
    if app in MEDIA:
        media_paths()[0].mkdir(parents=True, mode=0o700, exist_ok=True)
    (run / "transport/exit-status").unlink(missing_ok=True)
    (run / "transport/theme").write_text(current_theme())
    (run / "transport/text-settings").write_text(json.dumps(current_font_preferences()))
    sound_preferences = {}
    for key in ["theme-name", "event-sounds", "input-feedback-sounds"]:
        result = subprocess.run([str(HERE.parent.parent / "bin/unity-quantal-runtime"), "/usr/bin/gsettings", "get",
                                 "org.gnome.desktop.sound", key], capture_output=True, text=True, timeout=10)
        sound_preferences[key] = (result.stdout.strip().strip("'") if key == "theme-name" else result.stdout.strip() == "true") \
            if result.returncode == 0 else ("ubuntu" if key == "theme-name" else True)
    (run / "transport/sounds").write_text(json.dumps(sound_preferences))
    (run / "passwd").write_text(f"legacy:x:{os.getuid()}:{os.getgid()}:Legacy application:/home/legacy:/bin/sh\n")
    (run / "group").write_text(f"legacy:x:{os.getgid()}:legacy\n")
    (run / "machine-id").write_text("a" * 32 + "\n")
    import shlex
    child = shlex.join([CONFIG["python"], "/runner/isolated.py", "worker", app, *files])
    xvfb = shlex.join([CONFIG["xvfb"], "+extension", "Composite", "-screen", "0", "1920x1200x24",
                      "-nolisten", "tcp", "-noreset", "-ac"])
    server_argv = base_namespace(run, app=app) + [CONFIG["xpra"], "start", ":100", *FEATURES,
        "--daemon=no", "--attach=no", "--use-display=no", "--systemd-run=no", "--start-via-proxy=no",
        "--mdns=no", "--html=off", "--http-scripts=off", "--pulseaudio=no", "--start-new-commands=no",
        "--socket-dir=/transport", "--socket-dirs=/transport", "--bind=/transport/app.sock",
        "--xvfb=" + xvfb, "--start-child=" + child, "--exit-with-children=yes", "--exit-with-client=yes"]
    client_argv = base_namespace(run, client=True) + [CONFIG["xpra"], "attach", "socket:///transport/app.sock",
        *FEATURES, "--title=@title@", "--reconnect=no", "--session-name=" + APPS[app], "--key-shortcut=none"] if attach else None
    with (run / "server.log").open("w") as server_log, (run / "client.log").open("w") as client_log:
        server = subprocess.Popen(server_argv, stdin=subprocess.DEVNULL, stdout=server_log, stderr=subprocess.STDOUT,
                                  start_new_session=True, preexec_fn=limits)
        client = None
        try:
            for _ in range(200):
                if server.poll() is not None:
                    raise RuntimeError("Isolated display failed to start; see " + str(run / "server.log"))
                if (run / "transport/app.sock").is_socket():
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError("Isolated display did not become ready")
            if attach:
                client = subprocess.Popen(client_argv, stdin=subprocess.DEVNULL, stdout=client_log,
                                          stderr=subprocess.STDOUT, start_new_session=True, preexec_fn=limits)
            while server.poll() is None:
                if client is not None and client.poll() is not None:
                    if client.returncode:
                        raise RuntimeError("Application display disconnected; see " + str(run / "client.log"))
                    break
                time.sleep(0.1)
        finally:
            for process in [server, client]:
                if process is not None and process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
    # Waiting for bubblewrap ends the PID namespace and all remaining children.
    status = run / "transport/exit-status"
    try:
        fd = os.open(status, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.read(fd, 32) != b"0":
            raise RuntimeError("Application exited unsuccessfully; see " + str(run / "server.log"))
    finally:
        os.close(fd)


def media(app):
    base = Path.home() / ".local/state/unity-quantal/isolated"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    # One instance per profile; a second launch leaves the running one alone.
    with (base / (app + ".lock")).open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        run = Path(tempfile.mkdtemp(prefix=app + "-", dir=base))
        run_session(run, app, [])
        shutil.rmtree(run)


def main(app, values, *, viewer_flags=()):
    if os.environ.get("XDG_CURRENT_DESKTOP") != "Unity":
        raise RuntimeError("These application defaults are for the Unity session")
    if app in MEDIA:
        return media(app)
    files = [local_file(value) for value in values]
    if app in ("eog", "file-roller") and not files:
        chosen = dialog("--file-selection", "--title=Open in " + APPS[app])
        if chosen is None:
            return
        files = [local_file(chosen)]
    base = Path.home() / ".local/state/unity-quantal/isolated"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    run = Path(tempfile.mkdtemp(prefix=app + "-", dir=base))
    for name in ["input", "output", "transport"]:
        (run / name).mkdir(mode=0o700)
    original = {}
    argv = []
    if app == "eog":
        images = image_inputs(files)
        mounts = []
        for index, source in enumerate(images):
            name = str(index + 1) + "-" + source.name if len(files) > 1 else source.name
            (run / "input" / name).touch(mode=0o600)
            mounts.append((str(source), name))
            if source in files:
                argv.append("/home/legacy/Input/" + name)
        (run / "images.json").write_text(json.dumps(mounts))
    for index, source in enumerate([] if app == "eog" else files):
        name = str(index + 1) + "-" + source.name if len(files) > 1 else source.name
        target = run / ("output" if app == "gedit" else "input") / name
        copy_regular(source, target)
        original[name] = digest(target)
        argv.append("/home/legacy/" + ("Documents/" if app == "gedit" else "Input/") + name)
    if app == "gedit" and not files:
        (run / "output/Untitled.txt").touch()
        original["Untitled.txt"] = digest(run / "output/Untitled.txt")
        argv = ["/home/legacy/Documents/Untitled.txt"]
    messages = {
        "gedit": "Edit this private copy and save it in Documents. After closing Text Editor, choose where to save the result on your system. Clipboard sharing is disabled.",
        "eog": "Images open read-only. To keep edits, use Save As in Documents; after closing Image Viewer, choose where to export them. Clipboard sharing is disabled.",
        "file-roller": "Extract or save files into Documents. After closing Archive Manager, choose where to export them. Clipboard sharing is disabled.",
    }
    notice = base / (app + "-workflow-v1")
    if app in messages and not notice.exists():
        if dialog("--info", "--title=" + APPS[app], "--text=" + messages[app]) is not None:
            notice.touch(mode=0o600)
    try:
        run_session(run, app, [*viewer_flags, *argv])
    except Exception as error:
        raise RuntimeError(str(error) + "\nPrivate documents are retained in " + str(run / "output")) from error
    retained = False
    outputs = regular_files(run / "output")
    if app in ("gedit", "eog"):
        for source in outputs:
            relative = str(source.relative_to(run / "output"))
            if original.get(relative) == digest(source):
                continue
            chosen = dialog("--file-selection", "--save", "--confirm-overwrite", "--title=Export saved document", "--filename=" + source.name)
            if chosen is None:
                retained = True
                continue  # Retain the private copy for recovery.
            copy_regular(source, Path(chosen).absolute())
    elif app == "file-roller" and outputs:
        chosen = dialog("--file-selection", "--directory", "--title=Choose where to export extracted files")
        if chosen is None:
            retained = True
        else:
            destination = Path(tempfile.mkdtemp(prefix="Extracted-", dir=chosen))
            for source in outputs:
                target = destination / source.relative_to(run / "output")
                target.parent.mkdir(parents=True, exist_ok=True)
                copy_regular(source, target)
    if retained:
        dialog("--info", "--no-markup", "--title=Private copy retained",
               "--text=Your unsaved results are in " + str(run / "output"))
    else:
        # Only this invocation's generated private directory is removed.
        shutil.rmtree(run)


if __name__ == "__main__":
    if sys.argv[1:2] == ["install"]:
        install_desktops(Path(sys.argv[2]))
        raise SystemExit(0)
    if sys.argv[1:2] == ["worker"] and sys.argv[2:3] and sys.argv[2] in APPS:
        worker(sys.argv[2], sys.argv[3:])
    parser = argparse.ArgumentParser()
    parser.add_argument("app", choices=APPS)
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()
    try:
        main(args.app, args.files)
    except Exception as error:
        print(str(error), file=sys.stderr)
        dialog("--error", "--no-markup", "--title=Application could not finish", "--text=" + str(error))
        raise SystemExit(1)
