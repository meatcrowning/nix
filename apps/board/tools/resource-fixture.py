#!/usr/bin/env python3
"""Retain a real goetia window over synthetic stores, offscreen only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix="goetia-resource-") as tmp:
    repo = Path(__file__).resolve().parents[3]
    root = Path(tmp)
    normal = root / "normal.md"
    stress = root / "stress.md"
    normal.write_text("# Board\n\n## NEEDS YOU\n\n## TO DO\n\n## IN FLIGHT\n\n## LANDED\n")
    needs = "".join(f"### Decision {n}\n- A\n- B\n\nIf unanswered: leave it alone.\n\n" for n in range(160))
    todo = "".join(f"- [ ] [agent] synthetic task {n}\n" for n in range(500))
    stress.write_text(f"# Board\n\n## NEEDS YOU\n\n{needs}## TO DO\n\n{todo}\n## IN FLIGHT\n\n## LANDED\n")
    for d in ("state", "config", "cache", "runtime", "home", "transcripts"):
        (root / d).mkdir(mode=0o700 if d == "runtime" else 0o755)
    env = os.environ.copy()
    env.update({"QT_QPA_PLATFORM": "offscreen", "BOARD_RESOURCE_FIXTURE": "1",
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "XDG_RUNTIME_DIR": str(root / "runtime"), "HOME": str(root / "home"),
                "DESK_SESSION": "hypr", "BOARD_RESOURCE_NORMAL_PATH": str(normal),
                "BOARD_RESOURCE_STRESS_PATH": str(stress),
                "BOARD_TRANSCRIPTS": str(root / "transcripts")})
    for key in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"):
        env.pop(key, None)
    if Path(sys.executable).resolve() == Path("/usr/bin/python3").resolve():
        for key in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH"):
            env.pop(key, None)
        env["QT_QPA_PLATFORMTHEME"] = ""
        env["QT_STYLE_OVERRIDE"] = ""
    subprocess.run(["bash", "-c", f'. "{repo}/tools/lib/session-guard.sh"; sg_require_offscreen'], check=True, env=env)
    raise SystemExit(subprocess.call([sys.executable, str(repo / "apps/board/main.py"), str(normal)], env=env))
