"""Seed preferences without touching earned stats; follow the active X display."""
import os
from pathlib import Path
import re
import subprocess
import sys


def prepare(game, spec_ops=False):
    config = game / ("players/iw4x_sp_config.cfg" if spec_ops else "players/iw4x_config.cfg")
    config.parent.mkdir(parents=True, exist_ok=True)
    text = config.read_text() if config.exists() else ""
    existing = set(re.findall(r"^\s*seta?\s+(\S+)", text, re.MULTILINE))
    defaults = {
        "gpad_enabled": 1, "gpad_style": 1, "gpad_haptics": 0,
        "gpad_light_bar": 0, "gpad_adaptive_triggers": 0,
        "r_fullscreen": 0, "r_noborder": 1, "r_aspectRatio": "auto",
        "com_maxfps": 120, "r_multiGpu": 0,
        "cg_fov": 80, "cl_autoRecord": 0,
        "bots_manage_fill": 12, "bots_manage_fill_mode": 0,
        "bots_skill": 3, "bots_main_chat": 0,
        "bots_main_firstIsHost": 1,
        "scr_xpscale": 1, "scr_rankedmatch": 1,
    }
    if spec_ops:
        defaults = {
            "r_fullscreen": 0, "r_noBorder": 1, "r_aspectRatio": "auto",
            "com_maxfps": 120, "r_multiGpu": 0,
        }
    additions = [f'seta {key} "{value}"\n' for key, value in defaults.items()
                 if key not in existing]
    if additions:
        config.write_text(text.rstrip() + "\n" + "".join(additions))
    if spec_ops:
        return
    names = game / "mods/mp_bots/bots.txt"
    if not names.exists():
        names.parent.mkdir(parents=True, exist_ok=True)
        names.write_text("\n".join([
            "Archer", "Bishop", "Carter", "Dunn", "Foley", "Griffin",
            "Hunter", "Jackson", "Keegan", "Mitchell", "Noble", "Ramirez",
            "Roach", "Sandman", "Shepherd", "Woods", "Yuri", "Ghost",
        ]) + "\n")


def resolution():
    override = os.environ.get("MW2_RESOLUTION")
    if override is not None:
        if not re.fullmatch(r"[1-9]\d{2,4}x[1-9]\d{2,4}", override):
            raise ValueError("MW2_RESOLUTION must be WIDTHxHEIGHT")
        return override
    try:
        output = subprocess.check_output(
            ["xrandr", "--current"], text=True, stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""  # IW4x also detects the monitor on first launch.
    monitors = re.findall(
        r"^\S+ connected (primary )?(\d+x\d+)[+-]\d+[+-]\d+", output, re.MULTILINE)
    return next((size for primary, size in monitors if primary),
                monitors[0][1] if monitors else "")


if __name__ == "__main__":
    size = resolution()
    prepare(Path(sys.argv[1]), spec_ops="--spec-ops" in sys.argv[2:])
    print(size)
