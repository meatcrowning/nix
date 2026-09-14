#!/usr/bin/env python3
"""The session-resident desktop broker behind chatter's ``desktop_control``.

It deliberately is not the short-lived model code runner: applications are
started in their own process session and remain alive when chatter closes.  A
record is kept only for applications this broker launched; window-changing
verbs refuse anything else.
"""
import argparse
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path


def reply(conn, value):
    conn.sendall((json.dumps(value, separators=(",", ":")) + "\n").encode())


class Broker:
    def __init__(self, state, desktop_dirs, no_window_probe=False):
        self.state_path = Path(state)
        self.desktop_dirs = [Path(p) for p in desktop_dirs]
        self.no_window_probe = no_window_probe
        self.records = self._load()

    def _load(self):
        try:
            data = json.loads(self.state_path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.records, sort_keys=True) + "\n")
        os.replace(tmp, self.state_path)

    @staticmethod
    def _alive(pid):
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ValueError):
            return False

    def _desktop_entry(self, app):
        name = str(app or "").strip()
        if not name or "/" in name or ".." in name:
            raise ValueError("app must be a desktop entry id, not a command")
        names = [name] if name.endswith(".desktop") else [name + ".desktop", name]
        for root in self.desktop_dirs:
            for candidate in names:
                path = root / candidate
                if path.is_file():
                    return path
        raise ValueError("desktop entry not found: " + name)

    @staticmethod
    def _exec_from_entry(path):
        fields = {}
        in_entry = False
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line.startswith("["):
                in_entry = line == "[Desktop Entry]"
            elif in_entry and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                fields.setdefault(k, v)
        if fields.get("Type", "Application") != "Application" or fields.get("Hidden", "").lower() == "true":
            raise ValueError("desktop entry is not launchable")
        raw = fields.get("Exec", "")
        argv = [p for p in shlex.split(raw) if not (p.startswith("%") or "%" in p)]
        if not argv:
            raise ValueError("desktop entry has no executable Exec")
        return argv

    @staticmethod
    def _desktop_env():
        env = dict(os.environ)
        # A user service can outlive a compositor restart, so borrow current
        # Wayland/session variables from its real user processes each launch.
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                cmd = (proc / "comm").read_text().strip()
                if cmd not in ("kwin_wayland", "Hyprland", "plasmashell"):
                    continue
                raw = (proc / "environ").read_bytes().split(b"\0")
            except OSError:
                continue
            got = {}
            for item in raw:
                if b"=" in item:
                    k, v = item.split(b"=", 1)
                    got[k.decode("utf-8", "ignore")] = v.decode("utf-8", "ignore")
            if got.get("WAYLAND_DISPLAY") and got.get("XDG_RUNTIME_DIR"):
                for key in ("WAYLAND_DISPLAY", "DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "HYPRLAND_INSTANCE_SIGNATURE", "XDG_CURRENT_DESKTOP"):
                    if got.get(key):
                        env[key] = got[key]
                return env
        return env

    def _hypr_clients(self):
        if self.no_window_probe:
            return []
        wrapper = Path.home() / ".config/scripts/hypr-session-env.sh"
        if not wrapper.is_file():
            return []
        try:
            p = subprocess.run([str(wrapper), "/usr/sbin/hyprctl", "clients", "-j"],
                               capture_output=True, text=True, timeout=2)
            data = json.loads(p.stdout)
            return data if isinstance(data, list) else []
        except (OSError, ValueError, subprocess.SubprocessError):
            return []

    def _window(self, rec):
        pid = rec.get("pid")
        for c in self._hypr_clients():
            if c.get("pid") == pid:
                return {"backend": "hyprland", "id": c.get("address"),
                        "geometry": {"x": c.get("at", [0, 0])[0], "y": c.get("at", [0, 0])[1],
                                     "width": c.get("size", [0, 0])[0], "height": c.get("size", [0, 0])[1]},
                        "title": c.get("title", ""), "class": c.get("class", "")}
        return None

    @staticmethod
    def _plasma_available():
        try:
            p = subprocess.run(["qdbus", "org.kde.KWin", "/KWin"],
                               capture_output=True, text=True, timeout=1)
            return p.returncode == 0 and "org.kde.KWin" in p.stdout
        except (OSError, subprocess.SubprocessError):
            return False

    def _kwin_apply(self, rec, action, geometry=None):
        """Run a one-shot KWin script against this broker-owned PID.

        KWin deliberately exposes no arbitrary Wayland window-control D-Bus
        API. Its supported scripting API is the narrow compositor bridge here.
        The generated script contains only integers and our own stored PID;
        user/model text is never executed as JavaScript.
        """
        if self.no_window_probe or not self._plasma_available():
            return None
        pid = int(rec["pid"]); geometry = geometry or {}
        if action == "focus":
            body = "workspace.activeWindow = w;"
        elif action == "close":
            body = "w.closeWindow();"
        elif action == "move":
            body = "w.frameGeometry = {x:%d,y:%d,width:w.width,height:w.height};" % (geometry["x"], geometry["y"])
        else:
            body = "w.frameGeometry = {x:w.x,y:w.y,width:%d,height:%d};" % (geometry["width"], geometry["height"])
        ident = "oracle_desktop_control_" + uuid.uuid4().hex
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())) / "oracle-desktop-control"
        runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        script = runtime / (ident + ".js")
        script.write_text("for (const w of workspace.stackingOrder) { if (w.pid === %d) { %s break; } }\n" % (pid, body))
        try:
            load = subprocess.run(["qdbus", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript", str(script), ident],
                                  capture_output=True, text=True, timeout=2)
            start = subprocess.run(["qdbus", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.start"],
                                   capture_output=True, text=True, timeout=2)
            subprocess.run(["qdbus", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", ident],
                           capture_output=True, text=True, timeout=2)
            return load.returncode == 0 and start.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
        finally:
            try: script.unlink()
            except OSError: pass

    def _status(self, handle, rec):
        alive = self._alive(rec.get("pid"))
        win = self._window(rec) if alive else None
        return {"ok": True, "handle": handle, "app": rec["app"], "pid": rec["pid"],
                "owned": True, "state": "window_observed" if win else ("process_running_no_window" if alive else "process_exited"),
                "window": win}

    def launch(self, req):
        entry = self._desktop_entry(req.get("app"))
        argv = self._exec_from_entry(entry)
        state_dir = self.state_path.parent
        state_dir.mkdir(parents=True, exist_ok=True)
        log = state_dir / ("desktop-" + uuid.uuid4().hex + ".log")
        with log.open("ab", buffering=0) as out:
            proc = subprocess.Popen(argv, cwd=str(Path.home()), env=self._desktop_env(),
                                    stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                                    start_new_session=True, close_fds=True)
        handle = "desk-" + uuid.uuid4().hex[:12]
        rec = {"app": entry.name, "argv": argv, "pid": proc.pid, "started": int(time.time()), "log": str(log)}
        self.records[handle] = rec
        self._save()
        # An event-loop based GUI normally maps in this interval. Never claim it
        # did merely because Popen returned.
        deadline = time.monotonic() + min(max(float(req.get("wait", 2)), 0), 5)
        while time.monotonic() < deadline and self._alive(proc.pid):
            if self._window(rec):
                break
            time.sleep(.1)
        return self._status(handle, rec)

    def act(self, req):
        action = str(req.get("action", "")).strip()
        if action == "list":
            return {"ok": True, "windows": [self._status(k, v) for k, v in self.records.items()]}
        handle = str(req.get("handle", ""))
        rec = self.records.get(handle)
        if not rec:
            return {"ok": False, "error": "unknown or non-agent-owned handle"}
        if action == "inspect":
            return self._status(handle, rec)
        if action == "close":
            win = self._window(rec)
            if win and win["backend"] == "hyprland":
                cmd = ["dispatch", "closewindow", "address:" + str(win["id"])]
                p = subprocess.run([str(Path.home() / ".config/scripts/hypr-session-env.sh"), "/usr/sbin/hyprctl"] + cmd,
                                   capture_output=True, text=True, timeout=2)
                return {"ok": p.returncode == 0, "handle": handle, "action": "close_requested", "verified": False}
            plasma = self._kwin_apply(rec, "close")
            if plasma is not None:
                return {"ok": plasma, "handle": handle, "action": "close_requested", "verified": False,
                        "note": "submitted through KWin's scripting API; inspect to check whether the application accepted it"}
            return {"ok": False, "error": "no controllable window was observed; refusing to signal a GUI process because it may have unsaved work"}
        win = self._window(rec)
        if not win:
            geom = req.get("geometry") if isinstance(req.get("geometry"), dict) else {}
            if action in ("move", "resize"):
                need = ("x", "y") if action == "move" else ("width", "height")
                if not all(isinstance(geom.get(k), int) for k in need):
                    return {"ok": False, "error": action + " needs integer geometry." + need[0] + " and geometry." + need[1]}
            plasma = self._kwin_apply(rec, action, geom)
            if plasma is not None:
                return {"ok": plasma, "handle": handle, "action": action, "verified": False,
                        "note": "submitted through KWin's scripting API; inspect to check the process remains running"}
            return {"ok": False, "error": "no controllable window was observed for this handle"}
        if action == "focus":
            words = ["dispatch", "focuswindow", "address:" + str(win["id"])]
        elif action in ("move", "resize"):
            geom = req.get("geometry") if isinstance(req.get("geometry"), dict) else {}
            if action == "move":
                x, y = geom.get("x"), geom.get("y")
                if not isinstance(x, int) or not isinstance(y, int):
                    return {"ok": False, "error": "move needs integer geometry.x and geometry.y"}
                words = ["dispatch", "movewindowpixel", "exact", str(x), str(y), "address:" + str(win["id"])]
            else:
                w, h = geom.get("width"), geom.get("height")
                if not isinstance(w, int) or not isinstance(h, int) or w < 64 or h < 64:
                    return {"ok": False, "error": "resize needs geometry.width and geometry.height of at least 64"}
                words = ["dispatch", "resizewindowpixel", "exact", str(w), str(h), "address:" + str(win["id"])]
        else:
            return {"ok": False, "error": "unknown action"}
        p = subprocess.run([str(Path.home() / ".config/scripts/hypr-session-env.sh"), "/usr/sbin/hyprctl"] + words,
                           capture_output=True, text=True, timeout=2)
        result = self._status(handle, rec)
        result.update({"ok": p.returncode == 0, "action": action, "verified": p.returncode == 0})
        return result


def main():
    ap = argparse.ArgumentParser()
    runtime = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    ap.add_argument("--socket", default=runtime + "/oracle-desktop-control.sock")
    ap.add_argument("--state", default=str(Path.home() / ".local/state/oracle/desktop-control.json"))
    ap.add_argument("--desktop-dir", action="append", default=[])
    ap.add_argument("--no-window-probe", action="store_true")
    args = ap.parse_args()
    dirs = args.desktop_dir or [str(Path.home() / ".local/share/applications"), "/usr/share/applications", "/run/current-system/sw/share/applications"]
    broker = Broker(args.state, dirs, args.no_window_probe)
    path = Path(args.socket)
    path.parent.mkdir(parents=True, exist_ok=True)
    try: path.unlink()
    except FileNotFoundError: pass
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path)); os.chmod(path, 0o600); server.listen()
        while True:
            conn, _ = server.accept()
            with conn:
                try:
                    req = json.loads(conn.recv(65536).decode())
                    action = str(req.get("action", ""))
                    value = broker.launch(req) if action == "launch" else broker.act(req)
                except Exception as exc:
                    value = {"ok": False, "error": str(exc)}
                reply(conn, value)


if __name__ == "__main__":
    main()
