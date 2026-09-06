#!/usr/bin/env python3
"""Retain Painter gallery states using tiny synthetic local PNG outputs."""
import base64
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
with tempfile.TemporaryDirectory(prefix="painter-resource-") as tmp:
    repo, root = Path(__file__).resolve().parents[3], Path(tmp)
    for d in ("state", "config", "cache", "runtime", "home", "out", "models"):
        (root / d).mkdir(mode=0o700 if d == "runtime" else 0o755)
    for i in range(900):
        (root / "out" / f"fixture_{i:04d}.png").write_bytes(PNG)
    env = os.environ.copy()
    env.update({"QT_QPA_PLATFORM": "offscreen", "PAINTER_RESOURCE_FIXTURE": "1",
                "PAINTER_OUT": str(root / "out"), "PAINTER_MODELS": str(root / "models"),
                "PAINTER_PEER_OUT": "", "XDG_STATE_HOME": str(root / "state"),
                "XDG_CONFIG_HOME": str(root / "config"), "XDG_CACHE_HOME": str(root / "cache"),
                "XDG_RUNTIME_DIR": str(root / "runtime"), "HOME": str(root / "home"),
                "DESK_SESSION": "hypr"})
    for key in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"):
        env.pop(key, None)
    if Path(sys.executable).resolve() == Path("/usr/bin/python3").resolve():
        for key in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH"):
            env.pop(key, None)
        env["QT_QPA_PLATFORMTHEME"] = ""
        env["QT_STYLE_OVERRIDE"] = ""
    subprocess.run(["bash", "-c", f'. "{repo}/tools/lib/session-guard.sh"; sg_require_offscreen'], check=True, env=env)
    raise SystemExit(subprocess.call([sys.executable, str(repo / "apps/painter/main.py")], env=env))
