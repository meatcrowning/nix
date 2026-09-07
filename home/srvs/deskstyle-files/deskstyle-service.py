#!/usr/bin/env python3
"""The session D-Bus authority for one desktop appearance transaction.

This is deliberately a small coordinator around the established wal pipeline,
not another wallpaper renderer.  A caller receives a monotonically increasing
generation immediately; the service emits real phase changes and only calls a
generation complete after the wallpaper pipeline and every participant that
was registered at the start has acknowledged the exact profile digest.

Interface: ``org.lam.DeskStyle1`` at ``/org/lam/DeskStyle1``.

``Apply(path) -> generation`` queues the newest request while an older one is
running. Custom apps register and acknowledge over the versioned, one-way
AF_UNIX protocol in ``apps/pylib/styleparticipant.py``. Unknown or late
acknowledgements are ignored: a stale repaint must never complete a newer
transaction.

The service starts with the graphical session but has no visual side effect
until ``Apply`` is called. It does not restart Plasma or synthesize UI actions;
wal-set.sh remains the sole live writer, but its prepared mode consumes the
controller-validated cache rather than doing extraction or scheme minting in
the visible apply phase.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import logging
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import threading
import time
from typing import Any

HERE = Path(__file__).resolve()
for candidate in (HERE.parents[3] / "apps" / "pylib", Path("/home/lam/nix/apps/pylib")):
    if candidate.is_dir():
        sys.path.insert(0, str(candidate))
        break

from styleprofile import StyleProfile, write_profile  # noqa: E402
from styleparticipant import PROTOCOL_VERSION, SOCKET_NAME, runtime_dir  # noqa: E402


BUS_NAME = "org.lam.DeskStyle1"
OBJECT_PATH = "/org/lam/DeskStyle1"
INTERFACE = "org.lam.DeskStyle1"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "deskstyle"
PROFILE_PATH = STATE_DIR / "active-profile.json"
STATUS_PATH = STATE_DIR / "status.json"
ACK_TIMEOUT_SECONDS = 12
IMAGE_SUFFIXES = frozenset((".png", ".jpg", ".jpeg", ".webp", ".bmp"))
LOG = logging.getLogger("deskstyle")


def wallpaper_library() -> Path:
    """Return the one collection DeskStyle is permitted to make active.

    The D-Bus endpoint is session-wide, so the UI's filtered model is not an
    authorization boundary.  Resolve both sides before comparing them: a
    symlink in the library must not turn Apply into a general arbitrary-file
    wallpaper writer.
    """
    configured = os.environ.get("DESKSTYLE_WALLPAPER_DIR")
    return Path(configured or (Path.home() / "Pictures" / "Wallpapers")).expanduser().resolve()


def authorized_wallpaper(value: str) -> Path:
    """Resolve and authorize one offered wallpaper, without side effects."""
    candidate = Path(value).expanduser().resolve(strict=True)
    library = wallpaper_library()
    if candidate.parent != library:
        raise ValueError("wallpaper must be a direct file in the wallpaper library")
    if candidate.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError("wallpaper type is not supported by DeskStyle")
    if not candidate.is_file():
        raise ValueError("wallpaper must name a regular file")
    return candidate


def elapsed_ms(started_at: float, now: float | None = None) -> float:
    """Return a non-negative whole-transaction duration from monotonic time."""
    return round(max(0.0, (time.monotonic() if now is None else now) - started_at) * 1000, 3)


def _pid_alive(pid: int) -> bool:
    """Whether a registered participant process can still acknowledge."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


NODE_XML = """<node>
  <interface name='org.lam.DeskStyle1'>
    <method name='Apply'>
      <arg type='s' name='wallpaper' direction='in'/>
      <arg type='u' name='generation' direction='out'/>
    </method>
    <method name='GetStatus'>
      <arg type='a{sv}' name='status' direction='out'/>
    </method>
    <signal name='Progress'>
      <arg type='u' name='generation'/><arg type='s' name='phase'/>
      <arg type='d' name='fraction'/><arg type='s' name='detail'/>
    </signal>
    <signal name='Completed'>
      <arg type='u' name='generation'/><arg type='s' name='profileHash'/>
      <arg type='b' name='allLive'/>
    </signal>
    <signal name='Superseded'>
      <arg type='u' name='generation'/><arg type='u' name='byGeneration'/>
    </signal>
    <signal name='Failed'>
      <arg type='u' name='generation'/><arg type='s' name='message'/>
    </signal>
  </interface>
</node>"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.isupper():
                result[key] = value
    except OSError:
        pass
    return result


def _scheme_name() -> str:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(Path.home() / ".config" / "kdeglobals", encoding="utf-8")
        return parser.get("General", "ColorScheme", fallback="OxygenDarkFlat")
    except (OSError, configparser.Error):
        return "OxygenDarkFlat"


def build_profile(generation: int, wallpaper: Path, color_scheme: str | None = None) -> StyleProfile:
    """Build the post-apply identity from wal's prepared cache, without UI IO."""
    key = hashlib.md5(str(wallpaper).encode("utf-8")).hexdigest()
    cache = Path.home() / ".cache" / "wal" / "themes"
    values = _read_env(cache / f"{key}.env")
    mode = _read_env(cache / f"{key}.mode").get("MODE", "scale")
    if mode not in {"scale", "tile"}:
        mode = "scale"
    # Keep the profile identity tied to the scheme whose prepared body this
    # transaction committed, rather than a later Colours KCM change racing the
    # post-apply read.
    scheme = color_scheme if color_scheme is not None else _scheme_name()
    scheme_file = Path.home() / ".local" / "share" / "color-schemes" / f"{scheme}.colors"
    palette_source = cache / f"{key}.env"
    return StyleProfile(
        generation=generation,
        wallpaper_path=str(wallpaper),
        wallpaper_sha256=_sha256(wallpaper),
        wallpaper_mode=mode,
        palette_sha256=_sha256(palette_source) if palette_source.is_file() else _sha256(wallpaper),
        accent="#" + values.get("ACCENT", "808080").lower(),
        color_scheme=scheme,
        color_scheme_sha256=_sha256(scheme_file) if scheme_file.is_file() else _sha256(wallpaper),
    )


def prepared_profile(wallpaper: Path, selected_scheme: str) -> dict[str, Any]:
    """Read and validate the cache record which may enter the live phase.

    Warming a cache is explicitly not an apply.  This validation keeps that
    boundary useful: a missing, stale, or partial cache is rejected before any
    wallpaper/KConfig writer runs, leaving the old desktop entirely live.
    """
    key = hashlib.md5(str(wallpaper).encode("utf-8")).hexdigest()
    manifest = Path.home() / ".cache" / "wal" / "profiles" / key / "manifest.json"
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"prepared profile is unreadable: {exc}") from exc
    if not isinstance(value, dict) or value.get("version") != 1:
        raise RuntimeError("prepared profile has an unsupported format")
    if value.get("source") != str(wallpaper):
        raise RuntimeError("prepared profile belongs to a different wallpaper")
    schemes = value.get("schemes")
    if not isinstance(schemes, dict) or schemes.get("ready") is not True:
        raise RuntimeError("prepared profile has no complete Plasma schemes")
    for name in ("dark", "darkNeutral", "light"):
        path = schemes.get(name)
        if not isinstance(path, str) or not Path(path).is_file():
            raise RuntimeError(f"prepared profile is missing its {name} scheme")
    # Only names with an exact pre-minted body may enter the short visible
    # transaction.  Falling back to dynamically minting an arbitrary selected
    # scheme makes the UI's "prepared" progress dishonest and can overwrite a
    # scheme DeskStyle does not own.
    scheme_keys = {
        "OxygenDarkFlat": "dark",
        "OxygenDarkNeutral": "darkNeutral",
        "OxygenLightFlat": "light",
        "Aero": "aero",
    }
    try:
        selected_key = scheme_keys[selected_scheme]
    except KeyError as exc:
        raise RuntimeError(f"selected color scheme is not prepared: {selected_scheme or '(none)'}") from exc
    selected_path = schemes[selected_key]
    if not isinstance(selected_path, str) or not Path(selected_path).is_file():
        raise RuntimeError(f"prepared profile is missing selected scheme: {selected_scheme}")
    value["selectedScheme"] = selected_scheme
    value["selectedSchemePath"] = selected_path
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


class DeskStyleService:
    def __init__(self, Gio: Any, GLib: Any) -> None:
        self.Gio, self.GLib = Gio, GLib
        self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.iface = Gio.DBusNodeInfo.new_for_xml(NODE_XML).lookup_interface(INTERFACE)
        self.conn.register_object(OBJECT_PATH, self.iface, self._on_call, None, None)
        self._lock = threading.Lock()
        self._next_generation = 0
        self._running: tuple[int, Path] | None = None
        self._queued: tuple[int, Path] | None = None
        # A registration belongs to a concrete process, not an application
        # name forever.  A crashed or closed app must not make every later
        # appearance transition wait for the acknowledgement timeout.
        self._participants: dict[str, int] = {}
        self._waiting: set[str] = set()
        self._profile: StyleProfile | None = None
        self._started_at: float | None = None
        self._status: dict[str, Any] = {"state": "idle", "generation": 0, "profileHash": ""}
        self._socket = self._bind_participant_socket()
        threading.Thread(target=self._participant_loop, daemon=True).start()
        self._write_status()

    def _bind_participant_socket(self) -> socket.socket:
        """Bind the private endpoint without unlinking a non-socket path."""
        directory = runtime_dir() / "deskstyle"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        endpoint = directory / SOCKET_NAME
        try:
            mode = endpoint.lstat().st_mode
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISSOCK(mode):
                raise RuntimeError(f"refusing to replace non-socket endpoint: {endpoint}")
            endpoint.unlink()
        old_mask = os.umask(0o077)
        try:
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(endpoint))
            server.listen(16)
            server.settimeout(1.0)
            return server
        finally:
            os.umask(old_mask)

    def _participant_loop(self) -> None:
        while True:
            try:
                connection, _ = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                try:
                    raw = bytearray()
                    while len(raw) <= 4096 and not raw.endswith(b"\n"):
                        block = connection.recv(min(1024, 4097 - len(raw)))
                        if not block:
                            break
                        raw.extend(block)
                    if len(raw) > 4096 or not raw.endswith(b"\n"):
                        continue
                    record = json.loads(bytes(raw).decode("utf-8"))
                    if not isinstance(record, dict) or record.get("version") != PROTOCOL_VERSION:
                        continue
                    self.GLib.idle_add(self._participant_record, record)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue

    def _participant_record(self, record: dict[str, Any]) -> bool:
        participant = record.get("participant")
        if not isinstance(participant, str) or not participant or len(participant) > 128:
            return False
        if record.get("type") == "register" and isinstance(record.get("pid"), int):
            self._participants[participant] = record["pid"]
            LOG.info("participant registered name=%s pid=%d", participant, record["pid"])
        elif record.get("type") == "acknowledge":
            self._acknowledge(record.get("generation"), participant, record.get("profileHash"))
        return False

    def _write_status(self) -> None:
        _atomic_json(STATUS_PATH, self._status)

    def _emit(self, signal: str, params: Any) -> None:
        self.conn.emit_signal(None, OBJECT_PATH, INTERFACE, signal, params)

    def _progress(self, generation: int, phase: str, fraction: float, detail: str) -> None:
        self._status.update({"state": phase, "generation": generation, "detail": detail,
                             "fraction": fraction})
        self._write_status()
        self._emit("Progress", self.GLib.Variant("(usds)", (generation, phase, fraction, detail)))

    def _variant_status(self) -> Any:
        values = {}
        for key, value in self._status.items():
            if isinstance(value, bool):
                values[key] = self.GLib.Variant("b", value)
            elif isinstance(value, int):
                values[key] = self.GLib.Variant("u", max(0, value))
            elif isinstance(value, float):
                values[key] = self.GLib.Variant("d", value)
            else:
                values[key] = self.GLib.Variant("s", str(value))
        return self.GLib.Variant("(a{sv})", (values,))

    def _on_call(self, _conn: Any, _sender: str, _object: str, _iface: str,
                 method: str, params: Any, invocation: Any) -> None:
        try:
            if method == "GetStatus":
                invocation.return_value(self._variant_status())
            elif method == "Apply":
                wallpaper = authorized_wallpaper(params.unpack()[0])
                generation = self._submit(wallpaper)
                invocation.return_value(self.GLib.Variant("(u)", (generation,)))
            else:
                invocation.return_dbus_error("org.lam.DeskStyle1.Error.UnknownMethod", method)
        except (OSError, ValueError) as exc:
            invocation.return_dbus_error("org.lam.DeskStyle1.Error.InvalidRequest", str(exc))

    def _submit(self, wallpaper: Path) -> int:
        with self._lock:
            self._next_generation += 1
            request = (self._next_generation, wallpaper)
            if self._running is not None:
                old = self._queued
                self._queued = request
                self._progress(request[0], "queued", 0.0, "Waiting for the current apply")
                if old is not None:
                    self._emit("Superseded", self.GLib.Variant("(uu)", (old[0], request[0])))
                return request[0]
            self._start_locked(request)
            return request[0]

    def _start_locked(self, request: tuple[int, Path]) -> None:
        self._running = request
        self._started_at = time.monotonic()
        # Participants are best-effort, but an exited client is certain not to
        # repaint. Drop it before taking this transaction's acknowledgement
        # snapshot so the overlay reflects only programs that can respond.
        self._participants = {
            participant: pid
            for participant, pid in self._participants.items()
            if _pid_alive(pid)
        }
        self._waiting = set(self._participants)
        LOG.info("apply generation=%d start participants=%s", request[0],
                 ",".join(sorted(self._waiting)) or "none")
        self._progress(request[0], "preparing", 0.02, "Validating prepared wallpaper and colors")
        threading.Thread(target=self._apply_worker, args=request, daemon=True).start()

    def _apply_worker(self, generation: int, wallpaper: Path) -> None:
        script = Path(os.environ.get("DESKSTYLE_WAL_SET", Path.home() / ".config" / "scripts" / "wal-set.sh"))
        prepare = Path(os.environ.get("DESKSTYLE_WAL_PREPARE", Path.home() / ".config" / "scripts" / "wal-prepare.sh"))
        try:
            if not script.is_file():
                raise RuntimeError(f"wallpaper apply script is unavailable: {script}")
            if not prepare.is_file():
                raise RuntimeError(f"wallpaper prepare script is unavailable: {prepare}")
            # This can be a cache hit (normally near-instant) or a first-use
            # warm-up.  Crucially it has no desktop-visible side effects.
            prepared_at = time.monotonic()
            prepared = subprocess.run([str(prepare), str(wallpaper)], text=True,
                                      capture_output=True, timeout=120, check=False)
            if prepared.returncode:
                raise RuntimeError((prepared.stderr or prepared.stdout or "wal-prepare failed").strip()[-600:])
            LOG.info("apply generation=%d prepared elapsedMs=%.1f", generation,
                     elapsed_ms(prepared_at))
            selected_scheme = _scheme_name()
            prepared_profile(wallpaper, selected_scheme)
            self.GLib.idle_add(self._progress, generation, "applying", 0.18,
                               "Switching the prepared wallpaper and colors")
            applied_at = time.monotonic()
            run = subprocess.run([str(script), "--prepared", "--scheme", selected_scheme, str(wallpaper)], text=True,
                                 capture_output=True, timeout=120, check=False)
            if run.returncode:
                raise RuntimeError((run.stderr or run.stdout or "wal-set failed").strip()[-600:])
            LOG.info("apply generation=%d desktopSwitch elapsedMs=%.1f", generation,
                     elapsed_ms(applied_at))
            profile = build_profile(generation, wallpaper, selected_scheme)
            write_profile(PROFILE_PATH, profile)
            self.GLib.idle_add(self._pipeline_finished, generation, profile)
        except Exception as exc:  # the D-Bus caller gets a terminal signal, never a hung apply
            self.GLib.idle_add(self._pipeline_failed, generation, str(exc))

    def _pipeline_finished(self, generation: int, profile: StyleProfile) -> bool:
        if self._running is None or self._running[0] != generation:
            return False
        self._profile = profile
        if self._queued is not None:
            queued = self._queued
            self._queued = None
            self._emit("Superseded", self.GLib.Variant("(uu)", (generation, queued[0])))
            self._start_locked(queued)
            return False
        if self._waiting:
            LOG.info("apply generation=%d waiting participants=%s", generation,
                     ",".join(sorted(self._waiting)))
            self._progress(generation, "waiting-for-apps", 0.9, ", ".join(sorted(self._waiting)))
            self.GLib.timeout_add_seconds(ACK_TIMEOUT_SECONDS, self._ack_timeout, generation, profile.digest)
        else:
            self._complete(generation, profile.digest, True)
        return False

    def _acknowledge(self, generation: Any, participant: str, profile_hash: Any) -> None:
        if self._running is None or self._profile is None or generation != self._running[0]:
            return
        if not isinstance(profile_hash, str) or profile_hash != self._profile.digest or participant not in self._waiting:
            return
        self._waiting.remove(participant)
        LOG.info("apply generation=%d acknowledged participant=%s remaining=%s", generation,
                 participant, ",".join(sorted(self._waiting)) or "none")
        if not self._waiting:
            self._complete(generation, profile_hash, True)

    def _ack_timeout(self, generation: int, profile_hash: str) -> bool:
        if self._running is not None and self._running[0] == generation and self._waiting:
            self._complete(generation, profile_hash, False)
        return False

    def _complete(self, generation: int, profile_hash: str, all_live: bool) -> None:
        # Completion includes the participant acknowledgement window, not just
        # the wallpaper helper subprocess.  A zero after waiting twelve seconds
        # would be a false performance claim.
        elapsed = elapsed_ms(self._started_at or time.monotonic())
        missing = ", ".join(sorted(self._waiting))
        self._waiting.clear()
        self._running = None
        self._started_at = None
        self._status = {"state": "complete", "generation": generation, "profileHash": profile_hash,
                        "allLive": all_live, "elapsedMs": elapsed, "deferred": missing}
        self._write_status()
        LOG.info("apply generation=%d complete elapsedMs=%.1f allLive=%s deferred=%s", generation,
                 elapsed, all_live, missing or "none")
        self._emit("Completed", self.GLib.Variant("(usb)", (generation, profile_hash, all_live)))

    def _pipeline_failed(self, generation: int, message: str) -> bool:
        if self._running is not None and self._running[0] == generation:
            self._running = None
            self._started_at = None
            self._waiting.clear()
            self._status = {"state": "failed", "generation": generation, "detail": message, "profileHash": ""}
            self._write_status()
            LOG.error("apply generation=%d failed detail=%s", generation, message)
            self._emit("Failed", self.GLib.Variant("(us)", (generation, message)))
            if self._queued is not None:
                queued = self._queued
                self._queued = None
                self._start_locked(queued)
        return False

    def run(self) -> None:
        loop = self.GLib.MainLoop()
        self.Gio.bus_own_name_on_connection(self.conn, BUS_NAME, self.Gio.BusNameOwnerFlags.NONE,
                                            lambda *_: None, lambda *_: loop.quit())
        loop.run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DeskStyle session controller")
    parser.add_argument("--print-interface", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="deskstyle: %(message)s")
    if args.print_interface:
        print(NODE_XML)
        return 0
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
    except ImportError as exc:
        print(f"deskstyle-service: PyGObject is required: {exc}", file=sys.stderr)
        return 1
    DeskStyleService(Gio, GLib).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
