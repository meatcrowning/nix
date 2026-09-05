#!/usr/bin/env python3
"""Build the scheme-following Oxygen Plasma style from kdePackages.oxygen.

Run at nix build time: reads the stock desktoptheme out of the store, converts
every SVG (see oxyscheme.py) and writes a complete KPackage that carries NO
`colors` file -- which is the half that makes Plasma read the user's selected
colour scheme instead of the theme's own.
"""
import json, os, shutil, sys, glob
import oxyscheme

# Breeze deliberately leaves these baked -- they are illustrations, not chrome.
# branding.svgz is the only multi-hue raster in the theme (the KDE logo).
LEAVE_BAKED = {
    "widgets/branding.svgz", "widgets/monitor.svgz", "widgets/picker.svgz",
    "widgets/plot-background.svgz", "widgets/media-delegate.svgz",
    "widgets/dragger.svgz", "widgets/notes.svgz", "widgets/analog_meter.svgz",
}

METADATA = {
    "KPlugin": {
        "Id": "oxygen-scheme",
        "Name": "Oxygen (follows colour scheme)",
        "Description": "Oxygen, converted so its chrome takes the selected colour scheme",
        "License": "LGPL",
        "EnabledByDefault": True,
    },
    "X-Plasma-API": "5.0",
}

def main(src, out):
    os.makedirs(out, exist_ok=True)
    totals = {}
    for path in sorted(glob.glob(src + "/**/*.svgz", recursive=True)):
        rel = os.path.relpath(path, src)
        dst = os.path.join(out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if rel in LEAVE_BAKED:
            shutil.copyfile(path, dst); os.chmod(dst, 0o644)
            continue
        stats = oxyscheme.convert(path, dst)
        for k, v in stats.items():
            totals[k] = totals.get(k, 0) + v

    # plasmarc carries the theme's blur/compositing hints -- keep it.
    for extra in ("plasmarc",):
        p = os.path.join(src, extra)
        if os.path.exists(p):
            shutil.copyfile(p, os.path.join(out, extra))
            os.chmod(os.path.join(out, extra), 0o644)

    # NOTE: `colors` is deliberately NOT copied. Its presence is what pins a
    # Plasma style to its own palette; without it Plasma uses the user's scheme.
    assert not os.path.exists(os.path.join(out, "colors"))

    with open(os.path.join(out, "metadata.json"), "w") as f:
        json.dump(METADATA, f, indent=4)
    print("oxygen-scheme:", totals, file=sys.stderr)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
