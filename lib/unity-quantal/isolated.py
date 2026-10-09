"""Private X11 application sessions and explicit document import/export."""

import argparse
import configparser
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
APPS = {"gedit": "Text Editor", "eog": "Image Viewer", "file-roller": "Archive Manager", "gcalctool": "Calculator"}
MIMES = {
    "gedit": ["text/plain", "text/x-python", "text/x-nix", "text/x-lua", "text/x-c",
              "text/x-c++src", "text/x-c++hdr", "text/x-chdr", "text/x-csrc", "text/x-shellscript",
              "application/json", "application/x-shellscript", "text/x-qml", "text/x-diff",
              "text/x-patch", "text/csv", "application/xml", "text/xml"],
    "eog": ["image/png", "image/jpeg", "image/gif", "image/bmp", "image/tiff", "image/x-icon"],
    "file-roller": ["application/zip", "application/x-tar", "application/x-compressed-tar",
                    "application/x-bzip-compressed-tar", "application/x-xz-compressed-tar"],
    "gcalctool": [],
}
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
            "Exec": str(package / "bin/unity-quantal-isolated") + " " + app + " -- %F",
            "OnlyShowIn": "Unity;", "Terminal": "false", "StartupNotify": "false",
            "StartupWMClass": app, "Categories": "Utility;", "MimeType": ";".join(MIMES[app]) + ";",
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


def base_namespace(run, client=False):
    command = [CONFIG["bwrap"], "--die-with-parent", "--new-session", "--unshare-all", "--unshare-user",
               "--disable-userns", "--cap-drop", "ALL", "--tmpfs", "/",
               "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run", "--perms", "1777", "--dir", "/tmp/.X11-unix"]
    for path in Path(CONFIG["isolatedClosure"]).read_text().splitlines():
        command += ["--ro-bind", path, path]
    root = Path(CONFIG["runtime"])
    for name in ["bin", "sbin", "usr", "lib", "lib64", "etc", "var"]:
        if (root / name).exists():
            command += ["--ro-bind", str(root / name), "/" + name]
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
        command += ["--ro-bind", str(run / "input"), "/home/legacy/Input",
                    "--bind", str(run / "output"), "/home/legacy/Documents",
                    "--ro-bind", str(HERE / "isolated.py"), "/runner/isolated.py",
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
    environment = os.environ.copy()
    environment.update({
        "LD_LIBRARY_PATH": CONFIG["modernLibraries"] + ":/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:/usr/lib",
        "GSETTINGS_SCHEMA_DIR": "/usr/share/glib-2.0/schemas",
        "GDK_PIXBUF_MODULE_FILE": "/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders.cache",
        "GTK_THEME": "Ambiance", "UBUNTU_MENUPROXY": "0", "GIO_USE_VFS": "local",
        "GIO_EXTRA_MODULES": "", "GIO_MODULE_DIR": "/nonexistent", "GSETTINGS_BACKEND": "memory",
        "GTK_MODULES": "", "GTK_IM_MODULE": "gtk-im-context-simple",
        "PATH": CONFIG["archivePath"] + ":/usr/bin:/bin", "XDG_DATA_DIRS": "/usr/share",
    })
    settings = Path.home() / ".config/gtk-3.0/settings.ini"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("[Settings]\ngtk-theme-name=Ambiance\ngtk-icon-theme-name=ubuntu-mono-dark\ngtk-font-name=Ubuntu 11\n")
    (Path.home() / ".config/user-dirs.dirs").write_text('XDG_DOCUMENTS_DIR="$HOME/Documents"\nXDG_DOWNLOAD_DIR="$HOME/Documents"\nXDG_PICTURES_DIR="$HOME/Documents"\n')
    os.chdir("/home/legacy/Documents")
    bus_config = Path.home() / "bus.conf"
    bus_config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen><auth>EXTERNAL</auth><policy context="default"><allow send_destination="*"/><allow receive_sender="*"/><allow own="*"/></policy></busconfig>')
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


def run_session(run, app, files, *, attach=True):
    for name in ["input", "output", "transport"]:
        (run / name).mkdir(mode=0o700, exist_ok=True)
    (run / "transport/exit-status").unlink(missing_ok=True)
    (run / "passwd").write_text(f"legacy:x:{os.getuid()}:{os.getgid()}:Legacy application:/home/legacy:/bin/sh\n")
    (run / "group").write_text(f"legacy:x:{os.getgid()}:legacy\n")
    (run / "machine-id").write_text("a" * 32 + "\n")
    import shlex
    child = shlex.join([CONFIG["python"], "/runner/isolated.py", "worker", app, *files])
    xvfb = shlex.join([CONFIG["xvfb"], "+extension", "Composite", "-screen", "0", "1920x1200x24",
                      "-nolisten", "tcp", "-noreset", "-ac"])
    server_argv = base_namespace(run) + [CONFIG["xpra"], "start", ":100", *FEATURES,
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


def main(app, values):
    if os.environ.get("XDG_CURRENT_DESKTOP") != "Unity":
        raise RuntimeError("These application defaults are for the Unity session")
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
    for index, source in enumerate(files):
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
        run_session(run, app, argv)
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
