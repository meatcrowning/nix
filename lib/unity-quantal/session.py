"""Native session supervisor and FHS compatibility runtime for Unity 6.8."""

import configparser
import fcntl
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent.parent
CONFIG = json.loads((HERE / "config.json").read_text())
ROOT = Path(CONFIG["runtime"])
RUNTIME = str(PACKAGE / "bin/unity-quantal-runtime")
BRIDGES = ["unity-host-launch", "xdg-open", "gnome-session-quit",
           "gnome-screensaver-command", "x-terminal-emulator", "gnome-terminal"]


def desktop_parser(path):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return parser


def write_desktop(path, parser):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        parser.write(stream, space_around_delimiters=False)


def prepare(directory, environment):
    """Build session-local app and activation entries; never edit host entries."""
    data_dirs = environment.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    data_home = environment.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))
    state = {
        "data_dirs": data_dirs,
        "config_home": environment.get("XDG_CONFIG_HOME", str(Path.home() / ".config")),
        "data_home": data_home,
        "cache_home": environment.get("XDG_CACHE_HOME", str(Path.home() / ".cache")),
    }
    (directory / "state.json").write_text(json.dumps(state))
    for subdir in ["applications", "bridge-bin", "autostart", "native-data/dbus-1/services",
                   "native-data/cinnamon-session/sessions", "native-data/applications"]:
        (directory / subdir).mkdir(parents=True, exist_ok=True)
    for name in BRIDGES:
        target = directory / "bridge-bin" / name
        target.write_bytes((HERE / "bridge.py").read_bytes())
        target.chmod(0o755)

    seen = set()
    for parent in [data_home, *data_dirs]:
        for file in sorted((Path(parent) / "applications").glob("*.desktop")):
            if file.name in seen:
                continue
            seen.add(file.name)
            try:
                parser = desktop_parser(file)
            except (OSError, UnicodeError, configparser.Error):
                continue
            if "Desktop Entry" not in parser:
                continue
            terminal = parser["Desktop Entry"].get("Terminal", "false").lower() == "true"
            for section in parser.sections():
                entry = parser[section]
                if "Exec" in entry:
                    prefix = "/usr/local/bin/unity-host-launch --desktop " + shlex.quote(file.name)
                    if terminal and section == "Desktop Entry":
                        prefix += " --terminal"
                    entry["Exec"] = prefix + " -- " + entry["Exec"]
                entry.pop("TryExec", None)
            parser["Desktop Entry"]["DBusActivatable"] = "false"
            parser["Desktop Entry"]["Terminal"] = "false"
            write_desktop(directory / "applications" / file.name, parser)

    # The original settings panels configure Unity's private dconf profile.
    for file in (ROOT / "usr/share/applications").glob("gnome-*.desktop"):
        if file.name == "gnome-control-center.desktop" or file.name.endswith("-panel.desktop"):
            if file.name not in seen:
                (directory / "applications" / file.name).write_bytes(file.read_bytes())

    for file in (ROOT / "usr/share/dbus-1/services").glob("*.service"):
        parser = desktop_parser(file)
        entry = parser["D-BUS Service"]
        name = entry.get("Name", "")
        # The native services handle modern apps and the host's user database.
        if name == "ca.desrt.dconf" or name.startswith(("org.gtk.vfs.", "org.a11y.", "org.freedesktop.secrets")):
            continue
        if "Exec" in entry:
            entry["Exec"] = RUNTIME + " " + entry["Exec"]
            entry.pop("SystemdService", None)
            write_desktop(directory / "native-data/dbus-1/services" / file.name, parser)

    (directory / "native-data/cinnamon-session/sessions/unity-quantal.session").write_text(
        "[Cinnamon Session]\nName=Unity 12.10\n"
        "RequiredComponents=unity-quantal-settings;unity-quantal-shell;\nDesktopName=Unity\n"
    )
    components = {
        "unity-quantal-settings": (RUNTIME + " /usr/lib/gnome-settings-daemon/gnome-settings-daemon", "Initialization"),
        "unity-quantal-shell": (RUNTIME + " /usr/bin/compiz --replace ccp", "WindowManager"),
        "unity-quantal-locker": (CONFIG["screensaver"], "Application"),
        "unity-quantal-lock-api": (CONFIG["bridgePython"] + " " + str(HERE / "screensaver.py"), "Application"),
        "unity-quantal-polkit": (CONFIG["polkit"], "Application"),
        "unity-quantal-network": (CONFIG["network"] + " --indicator", "Application"),
        "unity-quantal-media-keys": (CONFIG["mediaKeys"], "Application"),
        "unity-quantal-power": (CONFIG["power"], "Application"),
    }
    for name, (command, phase) in components.items():
        text = (f"[Desktop Entry]\nType=Application\nName={name}\nExec={command}\n"
                f"X-GNOME-Autostart-Phase={phase}\nX-GNOME-AutoRestart=true\n"
                "NoDisplay=true\nOnlyShowIn=Unity;\n")
        (directory / "autostart" / (name + ".desktop")).write_text(text)
        (directory / "native-data/applications" / (name + ".desktop")).write_text(text)

    (directory / "applications/unity-quantal-terminal.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Terminal\nIcon=utilities-terminal\n"
        "Exec=/usr/local/bin/x-terminal-emulator\nCategories=System;TerminalEmulator;\n"
    )
    # Seed installed handlers once, instead of pinning missing 2012 applications.
    defaults = desktop_parser(Path(state["config_home"]) / "mimeapps.list")
    handlers = defaults["Default Applications"] if "Default Applications" in defaults else {}
    favorites = []
    for mime in ["inode/directory", "x-scheme-handler/http"]:
        for name in handlers.get(mime, "").split(";"):
            if name and (directory / "applications" / name).is_file():
                favorites.append("application://" + name)
                break
    favorites += ["application://unity-quantal-terminal.desktop",
                  "application://gnome-control-center.desktop",
                  "unity://running-apps", "unity://devices"]
    return favorites


def runtime(arguments):
    directory = Path(os.environ["UNITY_QUANTAL_SESSION_DIR"])
    state = json.loads((directory / "state.json").read_text())
    user_home = str(Path.home())
    cache = Path(state["cache_home"]) / "unity-quantal"
    data = Path(state["data_home"]) / "unity-quantal-session"
    for path in [cache, data, Path(state["config_home"]) / "dconf"]:
        path.mkdir(parents=True, exist_ok=True)
    command = [CONFIG["bwrap"], "--die-with-parent", "--unshare-net", "--tmpfs", "/"]
    for name in ["bin", "sbin", "usr", "lib", "lib64", "etc", "var"]:
        if (ROOT / name).exists():
            command += ["--ro-bind", str(ROOT / name), "/" + name]
    command += ["--ro-bind", "/nix", "/nix", "--proc", "/proc", "--dev-bind", "/dev", "/dev",
                "--ro-bind", "/sys", "/sys", "--tmpfs", "/tmp", "--tmpfs", "/run",
                "--bind", user_home, user_home,
                "--bind", os.environ["XDG_RUNTIME_DIR"], os.environ["XDG_RUNTIME_DIR"],
                "--ro-bind", "/tmp/.X11-unix", "/tmp/.X11-unix",
                "--ro-bind", str(directory / "applications"), "/usr/share/applications",
                "--ro-bind", str(directory / "bridge-bin"), "/usr/local/bin"]
    for path in ["/run/opengl-driver", "/run/current-system", "/run/dbus", "/run/udev", "/etc/profiles"]:
        if Path(path).exists():
            command += ["--ro-bind", path, path]
    if Path("/tmp/.ICE-unix").is_dir():
        command += ["--ro-bind", "/tmp/.ICE-unix", "/tmp/.ICE-unix"]
    for path in ["/etc/passwd", "/etc/group", "/etc/machine-id", "/etc/localtime"]:
        if Path(path).exists():
            command += ["--ro-bind", path, path]
    if Path("/etc/machine-id").exists():
        command += ["--ro-bind", "/etc/machine-id", "/var/lib/dbus/machine-id"]
    authority = os.environ.get("XAUTHORITY")
    if authority and Path(authority).is_file() and not authority.startswith(user_home + "/"):
        command += ["--ro-bind", authority, authority]
    # Keep every old child on the current loader; modern GL drivers require it.
    interpreter = ROOT / "lib64/ld-linux-x86-64.so.2"
    target = os.readlink(interpreter) if interpreter.is_symlink() else "/lib64/ld-linux-x86-64.so.2"
    command += ["--ro-bind", CONFIG["loader"], target]
    environment = {key: value for key, value in os.environ.items() if key in {
        "HOME", "USER", "LOGNAME", "DISPLAY", "XAUTHORITY", "ICEAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
        "XDG_RUNTIME_DIR", "SESSION_MANAGER", "DESKTOP_AUTOSTART_ID", "DESKTOP_STARTUP_ID",
        "PULSE_SERVER", "PULSE_COOKIE", "LANG", "LC_ALL", "UNITY_QUANTAL_HOST_SOCKET",
        "LOCALE_ARCHIVE", "LOCALE_ARCHIVE_2_27",
    }}
    environment.update({
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LD_LIBRARY_PATH": CONFIG["modernLibraries"] + ":/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:/usr/lib:/usr/lib/compiz:/usr/lib/x86_64-linux-gnu/libunity",
        "DESKTOP_SESSION": "ubuntu", "GDMSESSION": "ubuntu", "XDG_CURRENT_DESKTOP": "Unity",
        "XDG_SESSION_DESKTOP": "ubuntu", "XDG_SESSION_TYPE": "x11", "COMPIZ_CONFIG_PROFILE": "ubuntu",
        "XDG_CONFIG_HOME": state["config_home"], "XDG_CONFIG_DIRS": "/etc/xdg",
        "XDG_CACHE_HOME": str(cache), "XDG_DATA_HOME": str(data),
        "XDG_DATA_DIRS": "/usr/local/share:/usr/share:" + ":".join([state["data_home"], *state["data_dirs"]]),
        "DCONF_PROFILE": str(HERE / "dconf-profile"),
        "GSETTINGS_SCHEMA_DIR": "/usr/share/glib-2.0/schemas",
        "GDK_PIXBUF_MODULE_FILE": "/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders.cache",
        "GTK_THEME": "Ambiance",
    })
    # The runtime has no audio server of its own; speak to the host PipeWire socket.
    environment.setdefault("PULSE_SERVER", "unix:" + os.environ["XDG_RUNTIME_DIR"] + "/pulse/native")
    command += ["--clearenv"]
    for key, value in environment.items():
        command += ["--setenv", key, value]
    command += ["--chdir", user_home, *arguments]
    # D-Bus activation uses a short-lived intermediate parent. Give bubblewrap
    # a stable parent so --die-with-parent does not kill newly activated services.
    result = subprocess.run(command)
    if result.returncode:
        print(f"Unity runtime {arguments[0]} exited with {result.returncode}", file=sys.stderr)
    raise SystemExit(result.returncode if result.returncode >= 0 else 128 - result.returncode)


class LaunchServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path, environment, log):
        self.environment = environment
        self.log = log
        self.children = []
        super().__init__(str(path), LaunchRequest)


class LaunchRequest(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(5)
        _, uid, _ = struct.unpack("3i", self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid():
            return
        try:
            line = self.rfile.readline(65537)
            if len(line) > 65536:
                raise ValueError("Launch request is too large")
            request = json.loads(line)
            argv = request["argv"]
            if not isinstance(argv, list) or not all(isinstance(arg, str) for arg in argv):
                raise ValueError("Invalid application arguments")
            aliases = {"xdg-open": "open", "gnome-session-quit": "sessionQuit",
                       "gnome-screensaver-command": "screensaverCommand",
                       "x-terminal-emulator": "terminal", "gnome-terminal": "terminal"}
            environment = self.server.environment.copy()
            if request.get("startup_id"):
                environment["DESKTOP_STARTUP_ID"] = request["startup_id"]
            name = request["command"]
            if name in aliases:
                argv = [CONFIG[aliases[name]], *argv]
            elif name == "unity-host-launch":
                terminal = False
                while argv and argv[0] != "--":
                    option = argv.pop(0)
                    if option == "--desktop" and argv:
                        environment["BAMF_DESKTOP_FILE_HINT"] = "/usr/share/applications/" + argv.pop(0)
                    elif option == "--terminal":
                        terminal = True
                    else:
                        raise ValueError("Unknown launch option")
                if argv and argv[0] == "--":
                    argv.pop(0)
                if terminal:
                    argv = [CONFIG["terminal"], *argv]
            else:
                raise ValueError("Unknown launcher")
            if not argv:
                raise ValueError("No application specified")
            cwd = request.get("cwd", str(Path.home()))
            if not Path(cwd).is_dir():
                cwd = str(Path.home())
            child = subprocess.Popen(argv, env=environment, cwd=cwd,
                                     stdout=self.server.log, stderr=subprocess.STDOUT, start_new_session=True)
            self.server.children.append(child)
            threading.Thread(target=child.wait, daemon=True).start()
            result = {"pid": child.pid}
        except (OSError, ValueError, KeyError, IndexError) as error:
            result = {"error": str(error)}
        self.wfile.write((json.dumps(result) + "\n").encode())


def session():
    if not os.environ.get("DISPLAY"):
        raise RuntimeError("Select Unity 12.10 at the greeter; an X11 display is required")
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        raise RuntimeError("Refusing to replace a desktop inside a Wayland session; select Unity 12.10 at login")
    base = Path(os.environ["XDG_RUNTIME_DIR"]) / "unity-quantal-session"
    base.mkdir(mode=0o700, exist_ok=True)
    lock = (base / "session.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # Each login gets its own bus, app catalog, and launch socket.
    directory = base / str(os.getpid())
    directory.mkdir(mode=0o700)
    environment = os.environ.copy()
    for key in ["LD_LIBRARY_PATH", "GSETTINGS_SCHEMA_DIR", "DCONF_PROFILE",
                "GIO_EXTRA_MODULES", "SESSION_MANAGER", "DESKTOP_STARTUP_ID"]:
        environment.pop(key, None)
    environment.update({
        "UNITY_QUANTAL_SESSION_DIR": str(directory),
        "UNITY_QUANTAL_HOST_SOCKET": str(directory / "launch.sock"),
        "XDG_CURRENT_DESKTOP": "Unity", "XDG_SESSION_DESKTOP": "unity-quantal",
        "XDG_SESSION_TYPE": "x11", "DESKTOP_SESSION": "unity-quantal",
        "QT_QPA_PLATFORM": "xcb", "GDK_BACKEND": "x11",
        "PATH": CONFIG["hostPath"] + ":" + environment.get("PATH", ""),
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + str(directory / "bus"),
        "ICEAUTHORITY": str(directory / "ICEauthority"),
        "GI_TYPELIB_PATH": CONFIG["typelibs"] + ":" + environment.get("GI_TYPELIB_PATH", ""),
    })
    favorites = prepare(directory, environment)
    environment["XDG_DATA_DIRS"] = ":".join([
        str(directory / "native-data"), CONFIG["sessionData"],
        environment.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share"),
    ])
    service_dirs = [str(directory / "native-data/dbus-1/services"),
                    CONFIG["dconfServices"], CONFIG["vfsServices"]]
    bus_config = ("<busconfig><type>session</type><listen>" + escape(environment["DBUS_SESSION_BUS_ADDRESS"]) +
                  "</listen><auth>EXTERNAL</auth><standard_session_servicedirs/>" +
                  "".join("<servicedir>" + escape(path) + "</servicedir>" for path in service_dirs) +
                  '<policy context="default"><allow send_destination="*" eavesdrop="true"/>'
                  '<allow eavesdrop="true"/><allow own="*"/></policy></busconfig>')
    (directory / "bus.conf").write_text(bus_config)
    log_dir = Path(environment.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "unity-quantal"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = (log_dir / "session.log").open("w", buffering=1)
    bus = subprocess.Popen([CONFIG["dbus"], "--nofork", "--config-file=" + str(directory / "bus.conf")],
                           env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    manager = None
    server = None
    try:
        for _ in range(100):
            if (directory / "bus").exists():
                break
            if bus.poll() is not None:
                raise RuntimeError("Unity session bus failed; see " + str(log_dir / "session.log"))
            time.sleep(0.05)
        else:
            raise RuntimeError("Unity session bus did not become ready")
        server = LaunchServer(directory / "launch.sock", environment, log)
        os.chmod(directory / "launch.sock", 0o600)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        profile = Path(environment.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "dconf/unity_quantal"
        if not profile.exists():
            subprocess.run([RUNTIME, "/usr/bin/gsettings", "set", "com.canonical.Unity.Launcher",
                            "favorites", repr(favorites)], env=environment,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=10)
        # Hardware policy and media keys come from the native session. The old
        # daemon still supplies Unity's X settings, backgrounds, and keyboard.
        for plugin in ["power", "media-keys", "sound", "housekeeping"]:
            subprocess.run([RUNTIME, "/usr/bin/gsettings", "set", "org.gnome.settings-daemon.plugins." + plugin,
                            "active", "false"], env=environment, stdout=log, stderr=subprocess.STDOUT, check=False, timeout=10)
        manager = subprocess.Popen([CONFIG["session"], "--session=unity-quantal", "--autostart=" + str(directory / "autostart")],
                                   env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        def stop(_signum, _frame):
            if manager.poll() is None:
                manager.terminate()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        return manager.wait()
    finally:
        if manager is not None and manager.poll() is None:
            manager.terminate()
            try:
                manager.wait(timeout=10)
            except subprocess.TimeoutExpired:
                manager.kill()
                manager.wait()
        if server is not None:
            server.shutdown()
            server.server_close()
        processes = [bus, manager] + (server.children if server else [])
        for process in processes:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        try:
            bus.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bus.kill()
            bus.wait()
        log.close()


if __name__ == "__main__":
    if sys.argv[1:2] == ["runtime"]:
        runtime(sys.argv[2:])
    elif sys.argv[1:] == ["session"]:
        sys.exit(session())
    else:
        raise SystemExit("Usage: unity-quantal-session | unity-quantal-runtime COMMAND [ARGS]")
