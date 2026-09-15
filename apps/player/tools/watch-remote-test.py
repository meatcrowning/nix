#!/usr/bin/env python3
"""Regression test: remote libraries use SSH events, never CIFS watches.

The bug it guards: `AutoScanner._watch_dirs` runs on the GUI thread at startup
and every REWATCH_S, and used to `os.path.isdir(LIBRARY_ROOT)` +
`QFileSystemWatcher.addPath` on it unconditionally. On book LIBRARY_ROOT is the
`//top/aud` cifs mount over Tailscale, where a stat blocks the whole Qt event
loop for the CIFS timeout on any tailnet blip — the "random freeze". inotify
never propagates over cifs, so the watch was pure cost there anyway.

The fix gates the library root on `library_is_remote_cached()`:

  * remote library -> only the LOCAL slskd downloads dir is watched, and the
    watcher NEVER holds the library root (so no periodic stat of it);
  * local library  -> the library root is watched exactly as before.

Nothing here touches the live player: no Player is constructed (no libmpv, no
audio device), the roots are scratch dirs, and the platform is forced offscreen.

    QT_QPA_PLATFORM=offscreen /usr/bin/python3 apps/player/tools/watch-remote-test.py
"""
import os
import atexit
import sys
import tempfile
import shutil
import time
import json
from unittest.mock import patch
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

SCRATCH = tempfile.mkdtemp(prefix="player-watch-test-")
atexit.register(shutil.rmtree, SCRATCH, ignore_errors=True)
LIB = os.path.join(SCRATCH, "lib")
DOWNLOADS = os.path.join(SCRATCH, "downloads")
os.makedirs(LIB)
os.makedirs(DOWNLOADS)
os.environ["XDG_DATA_HOME"] = os.path.join(SCRATCH, "data")
os.environ["XDG_CACHE_HOME"] = os.path.join(SCRATCH, "cache")
os.environ["XDG_STATE_HOME"] = os.path.join(SCRATCH, "state")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(SCRATCH, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.environ["PLAYER_LIBRARY_ROOT"] = LIB

sys.path.insert(0, "/home/lam/nix/apps/player")
sys.path.insert(0, "/home/lam/nix/apps/pylib")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication([])
if app.platformName() != "offscreen":
    raise SystemExit("refusing to run on platform %r, not offscreen"
                     % app.platformName())

import main as P  # noqa: E402

# Point the module's roots at the scratch dirs (they were captured at import).
P.LIBRARY_ROOT = Path(LIB)
P.SLSKD_DOWNLOADS = Path(DOWNLOADS)

fails = []


def check(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "  FAIL") + f"  {name}: {got!r}"
          + ("" if ok else f"  != {want!r}"))
    if not ok:
        fails.append(name)


class FakeLibrary(QObject):
    """AutoScanner only needs scanRunning to connect and rescan to call."""
    scanRunning = Signal(bool)

    def __init__(self):
        super().__init__()
        self.rescans = 0

    def rescan(self):
        self.rescans += 1


def watched(remote):
    """Directories the AutoScanner holds after a _watch_dirs pass, with the
    library-remoteness answer forced to `remote`."""
    P._REMOTE_LIBRARY = remote          # bypass the mountinfo probe entirely
    walked = []
    walk = os.walk
    def observe(root, *args, **kwargs):
        walked.append(str(root))
        return walk(root, *args, **kwargs)
    with patch.object(P.os, "walk", observe):
        scanner = P.AutoScanner(FakeLibrary())
        scanner._import_timer.stop()  # never run the actual importer
        try:
            deadline = time.monotonic() + 2
            while scanner._watch_worker is not None and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.001)
            assert scanner._watch_worker is None, "watch discovery timed out"
            if remote:
                assert LIB not in walked, "remote root was traversed"
            return set(scanner._watcher.directories())
        finally:
            scanner._stop_watching()
            scanner.deleteLater()
            app.processEvents()


remote = watched(True)
check("remote: library root NOT watched", str(LIB) in remote, False)
check("remote: downloads dir watched", str(DOWNLOADS) in remote, True)

local = watched(False)
check("local: library root watched", str(LIB) in local, True)
check("local: downloads dir watched", str(DOWNLOADS) in local, True)

# A fake ssh executable proves three contracts without a live connection:
# bursts debounce to one scan, losing the stream reconnects, and reconnecting
# performs a catch-up scan for the blind interval. Its argv capture also keeps
# the remote command fixed and path-free apart from the declared library root.
bindir = os.path.join(SCRATCH, "bin")
os.makedirs(bindir)
fake_ssh = os.path.join(bindir, "ssh")
state = os.path.join(SCRATCH, "ssh-count")
argv_log = os.path.join(SCRATCH, "ssh-argv.jsonl")
Path(fake_ssh).write_text("""#!/usr/bin/env python3
import json, os, sys, time
state, log = os.environ['FAKE_SSH_STATE'], os.environ['FAKE_SSH_ARGV']
try:
    n = int(open(state).read())
except (OSError, ValueError):
    n = 0
open(state, 'w').write(str(n + 1))
with open(log, 'a') as f:
    f.write(json.dumps(sys.argv[1:]) + '\\n')
if n == 0:
    print('PLAYER_LIBRARY_READY')
    print('PLAYER_LIBRARY_CHANGED')
    print('PLAYER_LIBRARY_CHANGED')
    print('PLAYER_LIBRARY_CHANGED', flush=True)
    time.sleep(.15)
else:
    print('PLAYER_LIBRARY_READY', flush=True)
    time.sleep(2)
""")
os.chmod(fake_ssh, 0o755)
old_path = os.environ.get("PATH", "")
os.environ["PATH"] = bindir + os.pathsep + old_path
os.environ["FAKE_SSH_STATE"] = state
os.environ["FAKE_SSH_ARGV"] = argv_log
P.RemoteLibraryWatch.QUIET_MS = 30
P.RemoteLibraryWatch.RECONNECT_MS = 30
lib = FakeLibrary()
bridge = P.RemoteLibraryWatch(lib, "top-test")
deadline = time.monotonic() + 1.5
while lib.rescans < 2 and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(.005)
bridge.stop()
bridge.deleteLater()
app.processEvents()
calls = [json.loads(line) for line in Path(argv_log).read_text().splitlines()]
check("remote: event burst + reconnect catch-up scan", lib.rescans, 2)
check("remote: stream reconnected", len(calls) >= 2, True)
check("remote: fixed host", calls[0][-2], "top-test")
check("remote: fixed watch command", "exec inotifywait" in calls[0][-1], True)
check("remote: watches declared root", calls[0][-1].endswith(str(P.LIBRARY_ROOT)), True)
os.environ["PATH"] = old_path

print()
shutil.rmtree(SCRATCH)
if fails:
    print("FAILED:", ", ".join(fails))
    sys.exit(1)
print("all green")
