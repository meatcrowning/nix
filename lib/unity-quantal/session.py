"""Native session supervisor and FHS compatibility runtime for Unity 6.8."""

import configparser
import ctypes
import fcntl
import json
import os
import re
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
import integration
import isolated

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent.parent
CONFIG = json.loads((HERE / "config.json").read_text())
ROOT = Path(CONFIG["runtime"])
RUNTIME = str(PACKAGE / "bin/unity-quantal-runtime")
BRIDGES = ["unity-host-launch", "xdg-open", "gnome-session-quit",
           "gnome-screensaver-command", "x-terminal-emulator", "gnome-terminal"]
# Stable across rebuilds, so a live refresh or auto-restart runs current code.
DISPLAY_COMMAND = next(command for command in [
    "/run/current-system/sw/bin/unity-quantal-display", str(PACKAGE / "bin/unity-quantal-display")]
    if Path(command).exists())
ORIGINAL_APPS = ["nautilus", "gedit", "gnome-terminal", "gcalctool", "eog", "file-roller"]


def desktop_parser(path):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return parser


def write_desktop(path, parser):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        parser.write(stream, space_around_delimiters=False)
    temporary.replace(path)


def prepare(directory, environment):
    """Build session-local app and activation entries; never edit host entries."""
    data_dirs = environment.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    data_home = environment.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))
    state = {
        "data_dirs": data_dirs,
        "config_home": environment.get("XDG_CONFIG_HOME", str(Path.home() / ".config")),
        "data_home": data_home,
        "cache_home": environment.get("XDG_CACHE_HOME", str(Path.home() / ".cache")),
        "host_path": environment.get("PATH", CONFIG["hostPath"]),
        "host_shell": environment.get("SHELL", CONFIG["bash"]),
    }
    (directory / "state.json.tmp").write_text(json.dumps(state))
    (directory / "state.json.tmp").replace(directory / "state.json")
    for subdir in ["applications", "bridge-bin", "autostart", "native-data/dbus-1/services",
                   "native-data/cinnamon-session/sessions", "native-data/applications"]:
        (directory / subdir).mkdir(parents=True, exist_ok=True)
    for name in BRIDGES:
        target = directory / "bridge-bin" / name
        target.write_bytes((HERE / "bridge.py").read_bytes())
        target.chmod(0o755)

    seen = set()
    catalogs = [Path(parent) / "applications" for parent in [data_home, *data_dirs]]
    catalogs.append(Path.home() / "Desktop")
    for parent in catalogs:
        for file in sorted(parent.glob("*.desktop")):
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
                parser = desktop_parser(file)
                entry = parser["Desktop Entry"]
                entry["Exec"] = "/usr/local/bin/unity-host-launch --desktop " + file.name + " -- " + RUNTIME + " /usr/bin/" + entry["Exec"]
                entry["X-Unity-Original"] = "true"
                if file.name == "gnome-control-center.desktop":
                    entry["StartupWMClass"] = "Gnome-control-center"
                write_desktop(directory / "applications" / file.name, parser)

    integration.settings_entries(directory, ROOT, CONFIG, RUNTIME)

    for name in ORIGINAL_APPS:
        if name in isolated.APPS:
            file = "unity-original-" + name + ".desktop"
            parser = desktop_parser(PACKAGE / "share/applications" / file)
            entry = parser["Desktop Entry"]
            entry["Exec"] = "/usr/local/bin/unity-host-launch --desktop " + file + " -- " + entry["Exec"]
            entry["X-Unity-Original"] = "true"
            write_desktop(directory / "applications" / file, parser)
            continue
        source = ROOT / "usr/share/applications" / (name + ".desktop")
        if not source.exists():
            continue
        parser = desktop_parser(source)
        entry = parser["Desktop Entry"]
        entry["Name"] = entry.get("Name", name) + " (Ubuntu 12.10)"
        for key in list(entry):
            if key.startswith("Name[") or key in ["OnlyShowIn", "NotShowIn", "TryExec", "NoDisplay"]:
                del entry[key]
        entry["Exec"] = "/usr/bin/" + entry["Exec"]
        if name == "gnome-terminal":
            entry["Exec"] = "/usr/bin/gnome-terminal --disable-factory --command=/usr/local/bin/unity-native-shell"
        entry["Exec"] = "/usr/local/bin/unity-host-launch --desktop unity-original-" + name + ".desktop -- " + RUNTIME + " " + entry["Exec"]
        if name == "gnome-terminal":
            for section in parser.sections():
                if section != "Desktop Entry" and "Exec" in parser[section]:
                    parser[section]["Exec"] = entry["Exec"]
        entry["X-Unity-Original"] = "true"
        # The live shell may still have the previous read-only runtime mounted.
        # Absolute store paths let newly added original icons appear immediately.
        icons = list((ROOT / "usr/share/icons").rglob(entry.get("Icon", name) + ".png"))
        if icons:
            icons.sort(key=lambda p: (0 if "48x48" in p.parts or "48" in p.parts else 1, str(p)))
            entry["Icon"] = str(icons[0])
        entry["StartupWMClass"] = {"gnome-terminal": "Gnome-terminal", "nautilus": "Nautilus"}.get(name, name)
        write_desktop(directory / "applications" / ("unity-original-" + name + ".desktop"), parser)

    for profile, label in [("unity", "Unity default"), ("plasma", "Plasma feel")]:
        (directory / "applications" / ("unity-mouse-" + profile + ".desktop")).write_text(
            "[Desktop Entry]\nType=Application\nName=Mouse: " + label + "\nIcon=input-mouse\n"
            "Categories=Settings;HardwareSettings;X-GNOME-Settings-Panel;\n"
            "X-GNOME-Settings-Panel=unity-mouse-" + profile + "\n"
            "OnlyShowIn=Unity;\nExec=/usr/local/bin/unity-host-launch -- "
            + str(PACKAGE / "bin/unity-quantal-mouse") + " " + profile + "\n"
        )

    (directory / "applications/unity-display.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Brightness & Night Light\nIcon=preferences-desktop-display\n"
        "Categories=Settings;HardwareSettings;X-GNOME-Settings-Panel;\n"
        "X-GNOME-Settings-Panel=unity-host-display\nX-Unity-Original=true\n"
        "OnlyShowIn=Unity;\nExec=/usr/local/bin/unity-host-launch --desktop unity-display.desktop -- "
        + DISPLAY_COMMAND + " settings\n"
    )

    integration.host_icons(directory, state, CONFIG)
    isolated.install_defaults(state)
    integration.desktop_files(directory, state)
    integration.host_details(directory, ROOT)
    (directory / "gtk3").mkdir(exist_ok=True)
    (directory / "gtk3/settings.ini").write_text(
        "[Settings]\ngtk-theme-name=" + CONFIG["gtkTheme"] + "\ngtk-icon-theme-name=ubuntu-mono-dark\n"
        "gtk-font-name=Ubuntu 11\ngtk-application-prefer-dark-theme=false\n"
    )
    shell = directory / "bridge-bin/unity-native-shell"
    shell.write_text("#!/bin/sh\nexec /usr/bin/env -u LD_LIBRARY_PATH -u GSETTINGS_SCHEMA_DIR "
                     "-u GDK_PIXBUF_MODULE_FILE -u DCONF_PROFILE -u GTK_THEME "
                     + "PATH=" + shlex.quote(state["host_path"]) + " "
                     + "XDG_DATA_DIRS=" + shlex.quote(":".join(state["data_dirs"])) + " "
                     + "XDG_DATA_HOME=" + shlex.quote(state["data_home"]) + " "
                     + "XDG_CACHE_HOME=" + shlex.quote(state["cache_home"]) + " "
                     + "SHELL=" + shlex.quote(state["host_shell"]) + " "
                     + shlex.quote(state["host_shell"]) + " \"$@\"\n")
    shell.chmod(0o755)

    for file in (ROOT / "usr/share/dbus-1/services").glob("*.service"):
        parser = desktop_parser(file)
        entry = parser["D-BUS Service"]
        name = entry.get("Name", "")
        # The native services handle modern apps and the host's user database.
        if name == "ca.desrt.dconf" or name.startswith(("org.gtk.vfs.", "org.gtk.Private.", "org.a11y.", "org.freedesktop.secrets")):
            stale = directory / "native-data/dbus-1/services" / file.name
            if stale.exists():
                stale.unlink()
            continue
        if "Exec" in entry:
            entry["Exec"] = RUNTIME + " " + entry["Exec"]
            entry.pop("SystemdService", None)
            write_desktop(directory / "native-data/dbus-1/services" / file.name, parser)

    for file in Path(CONFIG["lockerServices"]).glob("*.service"):
        (directory / "native-data/dbus-1/services" / file.name).write_bytes(file.read_bytes())

    (directory / "native-data/cinnamon-session/sessions/unity-quantal.session").write_text(
        "[Cinnamon Session]\nName=Unity 12.10\n"
        "RequiredComponents=unity-quantal-settings;unity-quantal-shell;\nDesktopName=Unity\n"
    )
    components = {
        "unity-quantal-settings": (RUNTIME + " /usr/lib/gnome-settings-daemon/gnome-settings-daemon", "Initialization"),
        "unity-quantal-shell": (RUNTIME + " /usr/bin/compiz --replace ccp", "WindowManager"),
        "unity-quantal-locker": (CONFIG["screensaver"], "Application"),
        "unity-quantal-lock-api": (CONFIG["bridgePython"] + " " + str(HERE / "screensaver.py"), "Application"),
        "unity-quantal-window-icons": (CONFIG["python"] + " " + str(HERE / "session.py") + " window-icons", "Application"),
        "unity-quantal-polkit": (CONFIG["polkit"], "Application"),
        "unity-quantal-network": (CONFIG["network"] + " --indicator", "Application"),
        "unity-quantal-media-keys": (CONFIG["mediaKeys"], "Application"),
        "unity-quantal-power": (CONFIG["power"], "Application"),
        "unity-quantal-display": (DISPLAY_COMMAND + " indicator", "Application"),
    }
    for name, (command, phase) in components.items():
        text = (f"[Desktop Entry]\nType=Application\nName={name}\nExec={command}\n"
                f"X-GNOME-Autostart-Phase={phase}\nX-GNOME-AutoRestart=true\n"
                "NoDisplay=true\nOnlyShowIn=Unity;\n")
        (directory / "autostart" / (name + ".desktop")).write_text(text)
        (directory / "native-data/applications" / (name + ".desktop")).write_text(text)

    (directory / "applications/unity-quantal-terminal.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Terminal\nIcon=utilities-terminal\n"
        "Exec=/usr/local/bin/unity-host-launch --desktop unity-quantal-terminal.desktop -- "
        + str(PACKAGE / "bin/unity-quantal-terminal") + "\n"
        "Categories=System;TerminalEmulator;\nStartupWMClass=unity-terminal\n"
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
    command = [CONFIG["bwrap"], "--die-with-parent", "--tmpfs", "/"]
    # The original terminal must give its native shell ordinary network access.
    if arguments[0] != "/usr/bin/gnome-terminal":
        command += ["--unshare-net"]
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
    for source, target in [
        ("timezone", "/etc/timezone"),
        ("info.ui", "/usr/share/gnome-control-center/ui/info.ui"),
        ("clock.ui", "/usr/share/indicator-datetime/datetime-dialog.ui"),
        ("gtk3", state["config_home"] + "/gtk-3.0"),
        ("user-dirs.dirs", state["config_home"] + "/user-dirs.dirs"),
    ]:
        if arguments[0] == "/usr/bin/gnome-terminal" and source in ["gtk3", "user-dirs.dirs"]:
            continue
        if (directory / source).exists():
            command += ["--ro-bind", str(directory / source), target]
    for path in ["/run/opengl-driver", "/run/current-system", "/run/dbus", "/run/udev", "/etc/profiles"]:
        if Path(path).exists():
            command += ["--ro-bind", path, path]
    if Path("/tmp/.ICE-unix").is_dir():
        command += ["--ro-bind", "/tmp/.ICE-unix", "/tmp/.ICE-unix"]
    for path in ["/etc/passwd", "/etc/group", "/etc/machine-id", "/etc/localtime", "/etc/resolv.conf"]:
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
        "BAMF_DESKTOP_FILE_HINT",
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
    })
    if arguments[0] == "/usr/bin/gnome-terminal":
        # New tabs/windows do not inherit the initial --command override.
        # GNOME Terminal consults SHELL before falling back to /etc/passwd.
        environment["SHELL"] = "/usr/local/bin/unity-native-shell"
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
            if environment.get("BAMF_DESKTOP_FILE_HINT"):
                register_application(environment["BAMF_DESKTOP_FILE_HINT"], child.pid, environment)
            result = {"pid": child.pid}
        except (OSError, ValueError, KeyError, IndexError) as error:
            result = {"error": str(error)}
        self.wfile.write((json.dumps(result) + "\n").encode())


def drop_theme_bridges():
    # GTK 3.6 finds user themes only in ~/.themes. A live refresh onto a newer
    # runtime may link a theme there for the shell still on the old one; the
    # next login's runtime ships it, and a stale link would shadow updates.
    themes = Path.home() / ".themes"
    if not themes.is_dir():
        return
    for entry in themes.iterdir():
        if entry.is_symlink() and "-unity-12.10-original-runtime/" in os.readlink(entry):
            entry.unlink()
    if not any(themes.iterdir()):
        themes.rmdir()


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
    drop_theme_bridges()
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
            # Themes follow Appearance settings through XSETTINGS from here on.
            subprocess.run([RUNTIME, "/usr/bin/gsettings", "set", "org.gnome.desktop.interface",
                            "gtk-theme", repr(CONFIG["gtkTheme"])], env=environment,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=10)
        # Hardware policy and media keys come from the native session. The old
        # daemon still supplies Unity's X settings, backgrounds, and keyboard.
        for plugin in ["power", "media-keys", "sound", "housekeeping", "mouse"]:
            subprocess.run([RUNTIME, "/usr/bin/gsettings", "set", "org.gnome.settings-daemon.plugins." + plugin,
                            "active", "false"], env=environment, stdout=log, stderr=subprocess.STDOUT, check=False, timeout=10)
        apply_preferences(environment, log)
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


def apply_preferences(environment, log=None):
    # Work around stale partial repaints in the original Compiz/NVIDIA path.
    providers = subprocess.run([CONFIG["xrandr"], "--listproviders"], env=environment,
                               text=True, capture_output=True, timeout=5).stdout
    if "NVIDIA" in providers:
        for key in ["force-glx-sync", "force-swap-buffers"]:
            subprocess.run([RUNTIME, "/usr/bin/gsettings", "set",
                            "org.compiz.workarounds:/org/compiz/profiles/unity/plugins/workarounds/",
                            key, "true"], env=environment, check=True, stdout=log, stderr=log)
    # Meta drags windows: left button moves, right button resizes. The GNOME
    # modifier keys mirror it for the original apps and settings panels.
    # With GNOME integration on, Compiz reads these only at startup; a running
    # shell needs a restart (SIGTERM; cinnamon-session respawns it).
    for schema, key, value in [
            ("org.compiz.move:/org/compiz/profiles/unity/plugins/move/", "initiate-button", "'<Super>Button1'"),
            ("org.compiz.resize:/org/compiz/profiles/unity/plugins/resize/", "initiate-button", "'<Super>Button3'"),
            ("org.gnome.desktop.wm.preferences", "mouse-button-modifier", "'<Super>'"),
            ("org.gnome.desktop.wm.preferences", "resize-with-right-button", "true"),
            # Holding Meta opens the dash on release only, never the hints overlay.
            ("org.compiz.unityshell:/org/compiz/profiles/unity/plugins/unityshell/", "shortcut-overlay", "false")]:
        subprocess.run([RUNTIME, "/usr/bin/gsettings", "set", schema, key, value],
                       env=environment, check=True, stdout=log, stderr=log)
    integration.plasma_pointer(CONFIG, environment.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))


def refresh():
    if os.environ.get("XDG_CURRENT_DESKTOP") != "Unity" or os.environ.get("XDG_SESSION_TYPE") != "x11":
        raise RuntimeError("Refresh requires the running Unity X11 session")
    directory = Path(os.environ["UNITY_QUANTAL_SESSION_DIR"])
    state = json.loads((directory / "state.json").read_text())
    environment = os.environ.copy()
    environment["XDG_DATA_DIRS"] = ":".join(state["data_dirs"])
    prepare(directory, environment)
    subprocess.run([RUNTIME, "/usr/bin/gsettings", "set", "org.gnome.settings-daemon.plugins.mouse",
                    "active", "false"], env=environment, check=True)
    apply_preferences(environment)

    def bus(method, *arguments):
        return subprocess.run([CONFIG["gdbus"], "call", "--session", "--dest", "org.freedesktop.DBus",
                               "--object-path", "/org/freedesktop/DBus", "--method", "org.freedesktop.DBus." + method,
                               *arguments], env=environment, text=True, capture_output=True, timeout=10)

    bus("ReloadConfig")
    # Reapply app matching to windows already open, without moving them.
    window_icons(directory)
    clients = subprocess.check_output([CONFIG["xprop"], "-root", "_NET_CLIENT_LIST"], text=True)
    nautilus_windows = False
    for window in re.findall(r"0x[0-9a-fA-F]+", clients):
        props = subprocess.check_output([CONFIG["xprop"], "-id", window, "WM_CLASS", "_NET_WM_WINDOW_TYPE"], text=True)
        if '"Nautilus"' in props and "_NET_WM_WINDOW_TYPE_DESKTOP" not in props:
            nautilus_windows = True

    services = ["com.canonical.indicator.datetime", "org.freedesktop.Notifications", "org.ayatana.bamf", "com.canonical.Unity.Panel.Service"]
    if not nautilus_windows:
        services.append("org.gnome.Nautilus")
    else:
        print("Files windows are open; their desktop view will refresh when Files is next reopened")
    for name in services:
        owner = bus("GetConnectionUnixProcessID", name)
        match = re.search(r"uint32 (\d+)", owner.stdout)
        if match:
            pid = int(match[1])
            # Only terminate a service owned by our UID on this session's bus.
            if Path(f"/proc/{pid}").stat().st_uid == os.getuid():
                os.kill(pid, signal.SIGTERM)
                for _ in range(40):
                    if bus("GetConnectionUnixProcessID", name).stdout != owner.stdout:
                        break
                    time.sleep(0.05)
        activated = bus("StartServiceByName", name, "0")
        if activated.returncode:
            print(activated.stderr, file=sys.stderr)
    def launch(*argv):
        # The existing supervisor owns these helpers, so logout still reaps them.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(10)
            connection.connect(str(directory / "launch.sock"))
            request = {"command": "unity-host-launch", "argv": ["--", *argv]}
            connection.sendall((json.dumps(request) + "\n").encode())
            response = json.loads(connection.makefile().readline())
            if "error" in response:
                raise RuntimeError(response["error"])

    launch(CONFIG["python"], str(HERE / "session.py"), "window-icons")
    # Replace the display service. In a session that autostarted it, the
    # session manager restarts it through the stable command; a session that
    # predates it, or gave up restarting, gets it from the supervisor.
    owner = bus("GetConnectionUnixProcessID", "org.unity_quantal.Display")
    match = re.search(r"uint32 (\d+)", owner.stdout)
    if match and Path(f"/proc/{match[1]}").stat().st_uid == os.getuid():
        os.kill(int(match[1]), signal.SIGTERM)
        for _ in range(40):
            if bus("GetConnectionUnixProcessID", "org.unity_quantal.Display").stdout != owner.stdout:
                break
            time.sleep(0.05)
    for _ in range(40):
        if "uint32" in bus("GetConnectionUnixProcessID", "org.unity_quantal.Display").stdout:
            break
        time.sleep(0.05)
    else:
        launch(DISPLAY_COMMAND, "indicator")
    print("Updated Unity application catalog, icons, host details, pointer settings, and display service")


def register_application(desktop, pid, environment=None):
    try:
        subprocess.run([CONFIG["gdbus"], "call", "--session", "--dest", "org.ayatana.bamf",
                        "--object-path", "/org/ayatana/bamf/control", "--method",
                        "org.ayatana.bamf.control.RegisterApplicationForPid", desktop, str(pid)],
                       env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except subprocess.TimeoutExpired:
        pass  # Matching must not prevent an application from launching.


def window_icons(directory):
    matching = {}
    for desktop in sorted((directory / "applications").glob("*.desktop")):
        data = desktop_parser(desktop)
        if "Desktop Entry" not in data:
            continue
        entry = data["Desktop Entry"]
        if entry.get("NoDisplay", "false").lower() == "true":
            continue
        for name in [desktop.stem, desktop.stem.split(".")[-1]]:
            matching.setdefault(name.lower(), desktop.name)
    for desktop in sorted((directory / "applications").glob("*.desktop")):
        data = desktop_parser(desktop)
        name = data.get("Desktop Entry", "StartupWMClass", fallback="")
        if name:
            matching[name.lower()] = desktop.name
    clients = subprocess.run([CONFIG["xprop"], "-root", "_NET_CLIENT_LIST"], capture_output=True, text=True).stdout
    for window in re.findall(r"0x[0-9a-fA-F]+", clients):
        props = subprocess.run([CONFIG["xprop"], "-id", window, "WM_CLASS", "_NET_WM_DESKTOP_FILE", "_NET_WM_PID"], capture_output=True, text=True).stdout
        for name in re.findall(r'"([^"]+)"', props.splitlines()[0] if props else ""):
            filename = matching.get(name.lower())
            if filename:
                hint = "/usr/share/applications/" + filename
                if hint not in props:
                    subprocess.run([CONFIG["xprop"], "-id", window, "-f", "_NET_WM_DESKTOP_FILE", "8s", "-set",
                                    "_NET_WM_DESKTOP_FILE", hint], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    pid = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", props)
                    if pid:
                        register_application(hint, pid[1])
                break


class WindowAttributes(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p),
                ("root", ctypes.c_ulong), ("class_", ctypes.c_int), ("bit_gravity", ctypes.c_int),
                ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int), ("backing_planes", ctypes.c_ulong),
                ("backing_pixel", ctypes.c_ulong), ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong),
                ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long),
                ("your_event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
                ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p)]


def reframe_stranded_windows():
    # Compiz can leave a window minimized yet mapped outside any frame. It then
    # ignores activation, so the launcher cannot raise it and the window looks
    # lost off-screen. A minimized window Compiz still manages keeps its frame;
    # a fresh map makes Compiz manage the stranded one again.
    x = ctypes.CDLL(CONFIG["libX11"])
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    display = x.XOpenDisplay(None)
    if not display:
        return
    x.XDefaultRootWindow.restype = ctypes.c_ulong
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XInternAtom.restype = ctypes.c_ulong
    x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong] + [ctypes.POINTER(ctypes.c_ulong)] * 2 + [
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)), ctypes.POINTER(ctypes.c_uint)]
    x.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(WindowAttributes)]
    x.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long,
                                     ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                     ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                                     ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
    x.XFree.argtypes = [ctypes.c_void_p]
    for name in ["XUnmapWindow", "XMapWindow"]:
        getattr(x, name).argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    # Windows vanish between listing and inspection; never exit on BadWindow.
    ignore = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(lambda *_: 0)
    x.XSetErrorHandler(ignore)
    root = x.XDefaultRootWindow(display)
    wm_state = x.XInternAtom(display, b"WM_STATE", 0)
    client_list = x.XInternAtom(display, b"_NET_CLIENT_LIST", 0)

    def longs(window, atom):
        kind, size, count, after, data = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        if x.XGetWindowProperty(display, window, atom, 0, 4096, 0, 0, kind, size, count, after, data) != 0 or not data:
            return []
        values = list(ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[:count.value]) if size.value == 32 else []
        x.XFree(data)
        return values

    def stranded():
        found = set()
        parent, children, count = ctypes.c_ulong(), ctypes.POINTER(ctypes.c_ulong)(), ctypes.c_uint()
        if not x.XQueryTree(display, root, ctypes.byref(ctypes.c_ulong()), parent, children, count):
            return found
        tops = set(children[:count.value])
        if children:
            x.XFree(children)
        attributes = WindowAttributes()
        for window in tops & set(longs(root, client_list)):
            if (x.XGetWindowAttributes(display, window, attributes) and attributes.map_state == 2
                    and not attributes.override_redirect and longs(window, wm_state)[:1] == [3]):
                found.add(window)
        return found

    seen = set()
    while True:
        current = stranded()
        # A second sighting rules out a window caught mid-transition.
        repeated = current & seen
        for window in repeated:
            print("window-icons: re-framing stranded window " + hex(window), file=sys.stderr, flush=True)
            x.XUnmapWindow(display, window)
            x.XSync(display, 0)
            x.XMapWindow(display, window)
        x.XSync(display, 0)
        seen = current - repeated
        time.sleep(2)


def watch_windows():
    directory = Path(os.environ["UNITY_QUANTAL_SESSION_DIR"])
    lock = (directory / "window-icons.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    threading.Thread(target=reframe_stranded_windows, daemon=True).start()
    # Watch window membership only, never input, focus, or selection events.
    with subprocess.Popen([CONFIG["xprop"], "-spy", "-root", "_NET_CLIENT_LIST"], stdout=subprocess.PIPE, text=True) as watcher:
        for _ in watcher.stdout:
            window_icons(directory)


if __name__ == "__main__":
    if sys.argv[1:2] == ["runtime"]:
        runtime(sys.argv[2:])
    elif sys.argv[1:] == ["session"]:
        sys.exit(session())
    elif sys.argv[1:] == ["refresh"]:
        refresh()
    elif sys.argv[1:] == ["window-icons"]:
        watch_windows()
    elif sys.argv[1:2] == ["settings"] and len(sys.argv) == 3 and sys.argv[2] in CONFIG["settingsCommands"]:
        environment = os.environ.copy()
        environment["XDG_DATA_DIRS"] = CONFIG["settingsData"] + ":" + environment.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
        command = CONFIG["settingsCommands"][sys.argv[2]]
        os.execvpe(command[0], command, environment)
    elif sys.argv[1:2] == ["mouse"] and sys.argv[2:] in [["unity"], ["plasma"]]:
        if os.environ.get("XDG_CURRENT_DESKTOP") != "Unity" or os.environ.get("XDG_SESSION_TYPE") != "x11":
            raise SystemExit("Mouse profiles require the running Unity X11 session")
        integration.plasma_pointer(CONFIG, os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")), sys.argv[2])
        print("Mouse profile: " + sys.argv[2])
    else:
        raise SystemExit("Usage: unity-quantal-session | unity-quantal-runtime COMMAND [ARGS]")
