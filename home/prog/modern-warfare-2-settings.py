"""Seed preferences without touching earned stats; follow the active X display."""
import os
from pathlib import Path
import re
import subprocess
import sys


# These renderer preferences exist in both clients. Do not copy multiplayer's
# debug/render hooks, controller dvars, bindings, or progression settings.
SHARED_GRAPHICS = (
    "cg_fov", "cg_fovScale", "com_maxfps",
    "r_aaAlpha", "r_aaSamples", "r_aspectRatio", "r_customAspectRatio",
    "r_customMode", "r_mode", "r_fullscreen", "r_multiGpu", "r_gamma",
    "r_distortion", "r_dlightLimit", "r_dof_enable", "r_drawSun", "r_drawWater",
    "r_glow_allowed", "r_inGameVideo", "r_lodBiasRigid", "r_lodBiasSkinned",
    "r_lodScaleRigid", "r_lodScaleSkinned", "r_picmip", "r_picmip_bump",
    "r_picmip_manual", "r_picmip_spec", "r_picmip_water", "r_specular",
    "r_texFilterAnisoMax", "r_texFilterAnisoMin", "r_texFilterMipMode",
    "r_vsync", "r_zFeather", "sm_enable", "sm_maxLights",
)
SHARED_CONTROLLER = {
    "gpad_enabled": (1, 0, 1),
    "input_invertPitch": (0, 0, 1),
    "input_viewSensitivity": (1, .1, 5),
    "gpad_stick_deadzone_min": (.2, 0, .8),
    "gpad_stick_deadzone_max": (.01, 0, .1),
    "gpad_slowdown_enabled": (1, 0, 1),
    "gpad_lockon_enabled": (1, 0, 1),
    "aim_turnrate_yaw": (260, 0, 1000),
    "aim_turnrate_pitch": (90, 0, 1000),
    "aim_turnrate_yaw_ads": (90, 0, 1000),
    "aim_turnrate_pitch_ads": (55, 0, 1000),
}


def read_settings(config):
    return dict(re.findall(
        r'^\s*seta?\s+(\S+)\s+"([^"\r\n]*)"\s*$',
        config.read_text(), re.MULTILINE))


def import_spec_ops_graphics(config):
    marker = config.parent / ".mw2-sp-graphics-v1"
    multiplayer = config.parent / "iw4x_config.cfg"
    if marker.exists() or not multiplayer.exists():
        return
    values = read_settings(multiplayer)
    settings = {key: values[key] for key in SHARED_GRAPHICS if key in values}
    if "r_noborder" in values:
        settings["r_noBorder"] = values["r_noborder"]
    # SP resets these engine dvars on map load. Keep the chosen values separate
    # for the map initialization script to restore after that reset.
    for key in ("cg_fov", "cg_fovScale"):
        if key in settings:
            settings[key.replace("cg_", "mw2_sp_")] = settings[key]
    if not settings:
        return
    text = config.read_text() if config.exists() else ""
    backup = config.with_suffix(".cfg.before-mp-graphics")
    if config.exists() and not backup.exists():
        backup.write_text(text)
    for key, value in settings.items():
        pattern = rf'^\s*seta?\s+{re.escape(key)}\s+[^\r\n]*$'
        text = re.sub(pattern, "", text, flags=re.MULTILINE | re.IGNORECASE)
        text = text.rstrip() + f'\nseta {key} "{value}"\n'
    config.write_text(text)
    # Import once, so subsequent changes in the Spec Ops menu remain editable.
    marker.touch()


def spec_ops_arguments(game, size):
    values = read_settings(game / "players/iw4x_sp_config.cfg")
    # Hardware autoconfiguration runs after the profile is read. Restore the
    # snapshot afterward and restart the renderer to apply latched settings.
    # A cfg avoids the engine's limit on the number of +commands at startup.
    keys = (*SHARED_GRAPHICS, *SHARED_CONTROLLER, "r_noBorder", "mw2_sp_fov", "mw2_sp_fovScale")
    if size:
        values["r_mode"] = size
        yield from ("+set", "r_mode", size)
    startup = game / "spdata/nix_graphics.cfg"
    startup.parent.mkdir(parents=True, exist_ok=True)
    startup.write_text("".join(
        f'seta {key} "{values[key]}"\n' for key in keys if key in values
    ) + "vid_restart\n")
    yield from ("+exec", "nix_graphics.cfg")


def prepare(game, spec_ops=False):
    config = game / ("players/iw4x_sp_config.cfg" if spec_ops else "players/iw4x_config.cfg")
    config.parent.mkdir(parents=True, exist_ok=True)
    if spec_ops:
        import_spec_ops_graphics(config)
        marker = config.parent / ".mw2-sp-controller-v1"
        if not marker.exists():
            multiplayer = config.parent / "iw4x_config.cfg"
            values = read_settings(multiplayer) if multiplayer.exists() else {}
            text = config.read_text() if config.exists() else ""
            for key, (default, low, high) in SHARED_CONTROLLER.items():
                try:
                    value = float(values.get(key, default))
                except ValueError:
                    value = default
                if not low <= value <= high:
                    value = default
                text = re.sub(rf'^\s*seta?\s+{re.escape(key)}\s+[^\r\n]*$', "", text, flags=re.MULTILINE)
                text = text.rstrip() + f'\nseta {key} "{value:g}"\n'
            config.write_text(text)
            marker.touch()
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
    game = Path(sys.argv[1])
    prepare(game, spec_ops="--spec-ops" in sys.argv[2:])
    if "--launch-args" in sys.argv[2:]:
        print("\n".join(spec_ops_arguments(game, size)))
    else:
        print(size)
