#!/usr/bin/env python3
"""Retain real Player album models backed only by a synthetic database."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix="player-resource-") as tmp:
    repo, root = Path(__file__).resolve().parents[3], Path(tmp)
    for d in ("state", "config", "cache", "runtime", "home", "data", "aud"):
        (root / d).mkdir(mode=0o700 if d == "runtime" else 0o755)
    env = os.environ.copy()
    env.update({"QT_QPA_PLATFORM": "offscreen", "PLAYER_RESOURCE_FIXTURE": "1",
                "XDG_STATE_HOME": str(root / "state"), "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_CACHE_HOME": str(root / "cache"), "XDG_RUNTIME_DIR": str(root / "runtime"),
                "XDG_DATA_HOME": str(root / "data"), "HOME": str(root / "home"),
                "PLAYER_LIBRARY_ROOT": str(root / "aud"), "DESK_SESSION": "hypr"})
    for key in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"):
        env.pop(key, None)
    if Path(sys.executable).resolve() == Path("/usr/bin/python3").resolve():
        for key in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH"):
            env.pop(key, None)
        env["QT_QPA_PLATFORMTHEME"] = ""
        env["QT_STYLE_OVERRIDE"] = ""
    stub = root / "stub"
    stub.mkdir()
    (stub / "mpv.py").write_text("""\
class MPV:
    def __init__(self, **kw):
        self.volume=100; self.pause=True; self.playlist_count=0; self.playlist_pos=0
    def property_observer(self, name):
        return lambda fn: fn
    def command(self, *args): pass
""")
    env["PYTHONPATH"] = str(stub)
    # Let Player create its exact current schema once, then fill only the
    # albums table it reads for the retained grid.
    init = "import sys; sys.path.insert(0, %r); import main; c=main.open_db(); " \
           "c.executemany('INSERT INTO albums(album,album_artist,year,orig_year) VALUES(?,?,?,?)', " \
           "[(f'Album {i}',f'Artist {i%%80}',2000+i%%25,1990+i%%30) for i in range(1200)]); c.commit()" % str(repo / "apps/player")
    subprocess.run([sys.executable, "-c", init], check=True, env=env)
    subprocess.run(["bash", "-c", f'. "{repo}/tools/lib/session-guard.sh"; sg_require_offscreen'], check=True, env=env)
    raise SystemExit(subprocess.call([sys.executable, str(repo / "apps/player/main.py")], env=env))
