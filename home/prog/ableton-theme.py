#!/usr/bin/env python3
"""Give Wine controls and Ableton Live the current desktop palette."""

from __future__ import annotations

import re
import os
import configparser
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


HOME = Path.home()
THEME_QML = HOME / ".config/quickshell/Theme.qml"
PREFIX = HOME / ".wine"
KDEGLOBALS = HOME / ".config/kdeglobals"
LIVE = PREFIX / "drive_c/ProgramData/Ableton/Live 11 Suite"
THEMES = LIVE / "Resources/Themes"
PREFERENCES = (
    PREFIX
    / "drive_c/users/lam/AppData/Roaming/Ableton/Live 11.0/Preferences/Preferences.cfg"
)

TOKENS = (
    "bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
    "highlight", "ok", "warn", "crit", "info",
)


def palette() -> dict[str, str]:
    env_names = {
        "bg": "BG", "bgAlt": "BGALT", "border": "BORDER", "accent": "ACCENT",
        "dim": "DIM", "text": "TEXT", "textDim": "TEXTDIM",
        "highlight": "HIGHLIGHT", "ok": "OK", "warn": "WARN", "crit": "CRIT",
        "info": "INFO",
    }
    if all(os.environ.get(env_names[name], "").lstrip("#") for name in TOKENS):
        return {
            name: "#" + os.environ[env_names[name]].lstrip("#").lower()
            for name in TOKENS
        }
    text = THEME_QML.read_text(encoding="utf-8")
    found = dict(re.findall(
        r"readonly\s+property\s+color\s+(\w+):\s*[\"']#([0-9a-fA-F]{6})",
        text,
    ))
    missing = [name for name in TOKENS if name not in found]
    if missing:
        raise RuntimeError("missing Theme.qml colours: " + ", ".join(missing))
    return {name: "#" + found[name].lower() for name in TOKENS}


def rgb(value: str) -> str:
    return " ".join(str(int(value[i:i + 2], 16)) for i in (1, 3, 5))


def kde_color(group: str, key: str) -> str:
    """Read the same KColorScheme role the desktop's Qt apps use."""
    ini = configparser.ConfigParser(interpolation=None)
    ini.optionxform = str
    ini.read(KDEGLOBALS, encoding="utf-8")
    values = [int(value) for value in ini[group][key].split(",")]
    if len(values) != 3 or not all(0 <= value <= 255 for value in values):
        raise ValueError(f"invalid {group}/{key} in kdeglobals")
    return "#" + "".join(f"{value:02x}" for value in values)


def apply_wine(p: dict[str, str]) -> None:
    groups = {
        "ActiveBorder": "accent", "ActiveTitle": "accent",
        "AppWorkSpace": "bg", "Background": "bg", "ButtonDkShadow": "bg",
        "ButtonFace": "bgAlt", "ButtonHilight": "highlight",
        "ButtonLight": "highlight", "ButtonShadow": "border",
        "ButtonText": "text", "GradientActiveTitle": "accent",
        "GradientInactiveTitle": "border", "GrayText": "textDim",
        "Hilight": "accent", "HilightText": "bg", "HotTrackingColor": "accent",
        "InactiveBorder": "border", "InactiveTitle": "bgAlt",
        "InactiveTitleText": "textDim", "InfoText": "text",
        "InfoWindow": "bgAlt", "Menu": "bgAlt", "MenuBar": "bgAlt",
        "MenuHilight": "highlight", "MenuText": "text", "Scrollbar": "bgAlt",
        "TitleText": "bg", "Window": "bg", "WindowFrame": "border",
        "WindowText": "text",
    }
    reg = ["Windows Registry Editor Version 5.00", "", "[HKEY_CURRENT_USER\\Control Panel\\Colors]"]
    for key, token in groups.items():
        # USER32's native menu surface is the same semantic window background
        # as the Qt/Oxygen file menus around it, not the panel's bgAlt.
        value = kde_color("Colors:Window", "BackgroundNormal") \
            if key in ("Menu", "MenuBar") else p[token]
        reg.append(f'"{key}"="{rgb(value)}"')
    reg_path = HOME / ".cache/wine-desktop-theme.reg"
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text("\r\n".join(reg) + "\r\n", encoding="utf-16")
    subprocess.run(
        ["wine", "regedit", "/S", str(reg_path)],
        env={**os.environ, "WINEPREFIX": str(PREFIX)},
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def apply_ableton(p: dict[str, str]) -> None:
    source = THEMES / "03Dark.ask"
    target = THEMES / "Aero.ask"
    tree = ET.parse(source)
    theme = tree.getroot().find("Theme")
    if theme is None:
        raise RuntimeError(f"no Theme element in {source}")

    # Match the exact surfaces the other desktop apps use. kdetheme.py maps
    # their outer window to Colors:Window and inset views to Colors:View; the
    # panel palette is intentionally different in a Plasma session.
    p = {
        **p,
        "bg": kde_color("Colors:Window", "BackgroundNormal"),
        "bgAlt": kde_color("Colors:View", "BackgroundNormal"),
    }

    mapping = {
        "bg": ("MeterBackground", "SurfaceArea", "Desktop", "ScrollbarInnerTrack",
               "SceneContrast", "DisplayBackground", "ControlTextBack",
               "ControlContrastTransport", "ClipSlotButton", "RetroDisplayBackground"),
        "bgAlt": ("ControlBackground", "SurfaceBackground", "DetailViewBackground",
                  "PreferencesTab", "BrowserBar", "ScrollbarOuterTrack"),
        "highlight": ("SurfaceHighlight", "TakeLaneTrackHighlighted",
                      "RetroDisplayBackgroundLine", "InputCurveColor"),
        "border": ("ControlFillHandle", "ControlContrastFrame", "AutomationGrid",
                   "TakeLaneTrackNotHighlighted", "ScrollbarOuterHandle"),
        "dim": ("RangeDisabledOff", "DimmedWaveformColor"),
        "text": ("ControlForeground", "SurfaceAreaForeground", "SelectionFrame",
                 "ArrangementRulerMarkings", "DetailViewRulerMarkings",
                 "ControlOffForeground", "BrowserSampleWaveform", "LoopColor"),
        "textDim": ("TextDisabled", "ControlDisabled", "RangeDisabled",
                    "BrowserDisabledItem", "BrowserBarOverlayHintTextColor",
                    "ScrollbarInnerHandle", "ScrollbarLCDHandle", "ScrollbarLCDTrack"),
        "accent": ("ViewCheckControlEnabledOn", "ChosenDefault", "RangeDefault",
                   "BipolReset", "ChosenAlternative", "Progress", "TransportProgress",
                   "RetroDisplayForeground", "RetroDisplayGreen", "RetroDisplayHandle1",
                   "GainReductionLineColor", "AbletonColor"),
        "ok": ("ChosenPlay", "LearnMacro"),
        "warn": ("ChosenPreListen", "RetroDisplayForeground2", "ThresholdLineColor"),
        "crit": ("ChosenRecord", "AutomationColor", "VelocityColor", "Alert",
                 "ChosenAlert", "LearnKey"),
        "info": ("LearnMidi", "AutomationMouseOver", "SpectrumAlternativeColor"),
    }
    for token, names in mapping.items():
        for name in names:
            node = theme.find(name)
            if node is not None:
                alpha = node.get("Value", "")[7:9]
                node.set("Value", p[token] + alpha)

    ET.indent(tree, space="\t")
    tree.write(target, encoding="utf-8", xml_declaration=True)

    # Live's preferences format is proprietary. The selected theme is a UTF-16
    # string; Dark and our Aero name are deliberately the same width, so this
    # changes no offsets. Refuse if the file is not in the known state.
    if PREFERENCES.exists():
        data = PREFERENCES.read_bytes()
        old = "Dark".encode("utf-16le")
        new = "Aero".encode("utf-16le")
        if new not in data:
            if data.count(old) != 1:
                raise RuntimeError("cannot identify Live's selected Dark theme")
            PREFERENCES.write_bytes(data.replace(old, new, 1))


def main() -> int:
    if not LIVE.is_dir():
        return 0
    try:
        p = palette()
        apply_wine(p)
        apply_ableton(p)
    except Exception as exc:
        print(f"ableton-theme: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
