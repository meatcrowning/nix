#!/usr/bin/env python3
"""Pure palette checks: no Qt application, live files, or session writes."""
import configparser
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("scheme", ROOT / "home/srvs/wal-files/plasma-scheme.py")
scheme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scheme)
sys.path.insert(0, str(ROOT / "apps/pylib"))
import kdetheme

template = (ROOT / "home/prog/plasma-files/OxygenDarkFlat.colors").read_text()
def parse(body):
    ini = configparser.ConfigParser()
    ini.optionxform = str
    ini.read_string(body)
    return ini

for accent in ("ff0000", "00ff00", "0000ff", "808080", "d1a8a7"):
    for background in (None, "464540"):
        options = dict(background_hex=background, ui_accent_hex=accent)
        dark = parse(scheme.mint(template, accent, **options))
        light_template = (ROOT / "home/prog/plasma-files/OxygenLightFlat.colors").read_text()
        light = parse(scheme.mint(light_template, accent, ui_accent_hex=accent))
        mixed = parse(scheme.mint(template, accent, force_name="OxygenMixed", light_template=light_template, **options))
        for group in dark.sections():
            if group not in ("Colors:View", "General"):
                assert dict(mixed[group]) == dict(dark[group]), group
        assert dict(mixed["Colors:View"]) == dict(light["Colors:Window"])
        assert mixed["General"]["ColorScheme"] == "OxygenMixed"
        colors = kdetheme.kde_palette(dict(mixed))
        assert kdetheme._ratio(colors["text"], colors["bgAlt"]) >= kdetheme.TEXT_RATIO
        print("ok - mixed chrome matches dark; light native view:", accent, background)
