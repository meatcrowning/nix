"""A custom application's acknowledgement half of a live DeskStyle apply.

The controller owns applying desktop state.  A running app is only a
participant: it registers itself and acknowledges a profile *after* its own
palette reload callback has run on the Qt event loop.  This prevents a file
write from being mistaken for a repaint, while keeping a missing or restarted
controller completely out of the rendering path.

Protocol v1 is newline-delimited UTF-8 JSON over an AF_UNIX stream socket:

    $XDG_RUNTIME_DIR/deskstyle/participants.sock

Every record has ``version: 1`` and ``type``.  Participants send:

    {"version":1,"type":"register","participant":"player","pid":123}
    {"version":1,"type":"acknowledge","participant":"player",
     "generation":7,"profileHash":"<StyleProfile.digest>"}

The socket is deliberately best-effort and one-way.  Its directory belongs to
the logged-in user (the controller creates it mode 0700); clients never create
it, bind it, or retain a connection.  That makes a controller restart harmless
and avoids an app delaying its visible recolour on IPC.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
from typing import Callable

from styleprofile import ProfileError, read_profile


PROTOCOL_VERSION = 1
SOCKET_NAME = "participants.sock"
PROFILE_NAME = "active-profile.json"


def runtime_dir() -> Path:
    """The per-login runtime directory, never a persistent or shared path."""
    value = os.environ.get("XDG_RUNTIME_DIR")
    if value:
        return Path(value)
    return Path("/run/user") / str(os.getuid())


def socket_path() -> Path:
    return runtime_dir() / "deskstyle" / SOCKET_NAME


def profile_path() -> Path:
    override = os.environ.get("DESKSTYLE_PROFILE")
    if override:
        return Path(override)
    state = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return state / "deskstyle" / PROFILE_NAME


def encode_record(record_type: str, **fields) -> bytes:
    """Return one canonical protocol record, rejecting malformed callers."""
    if record_type not in ("register", "acknowledge"):
        raise ValueError("unsupported DeskStyle participant record")
    participant = fields.get("participant")
    if not isinstance(participant, str) or not participant:
        raise ValueError("participant must be a non-empty string")
    record = {"version": PROTOCOL_VERSION, "type": record_type, **fields}
    return (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def send_record(record: bytes, path: Path | None = None) -> bool:
    """Send a record without ever making a visual update depend on IPC."""
    target = str(path or socket_path())
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.05)
            client.connect(target)
            client.sendall(record)
        return True
    except OSError:
        return False


class StyleParticipant:
    """Qt event-loop bridge from an active profile to an app's real repaint.

    ``reload_palette`` must return true only after the app has read the source
    palette successfully.  It is called after a zero-delay event-loop turn so
    the profile's atomic replacement and the visual source's watcher settle in
    one coalesced repaint rather than an arbitrary sleep.
    """

    def __init__(self, participant: str, reload_palette: Callable[[], bool], parent=None):
        from PySide6.QtCore import QFileSystemWatcher, QTimer

        if not isinstance(participant, str) or not participant:
            raise ValueError("participant must be a non-empty string")
        self._participant = participant
        self._reload_palette = reload_palette
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._apply_current)
        self._watcher = QFileSystemWatcher(parent)
        self._watcher.fileChanged.connect(self._changed)
        self._watcher.directoryChanged.connect(self._changed)
        self._acknowledged: tuple[int, str] | None = None
        self._watch_paths()
        send_record(encode_record("register", participant=self._participant, pid=os.getpid()))
        self._schedule()

    def _watch_paths(self) -> None:
        path = profile_path()
        known = set(self._watcher.files()) | set(self._watcher.directories())
        for candidate in (path.parent, path):
            value = str(candidate)
            if candidate.exists() and value not in known:
                self._watcher.addPath(value)

    def _changed(self, _path: str) -> None:
        self._watch_paths()  # atomic replacement drops a file-only watch
        self._schedule()

    def _schedule(self) -> None:
        if not self._timer.isActive():
            self._timer.start(0)

    def _apply_current(self) -> None:
        self._watch_paths()
        try:
            profile = read_profile(profile_path())
        except ProfileError:
            return  # incomplete/absent state is not an acknowledgement
        identity = (profile.generation, profile.digest)
        if identity == self._acknowledged:
            return
        try:
            applied = self._reload_palette()
        except Exception:
            return
        if applied is not True:
            return
        record = encode_record("acknowledge", participant=self._participant,
                               generation=profile.generation, profileHash=profile.digest)
        send_record(record)
        self._acknowledged = identity
