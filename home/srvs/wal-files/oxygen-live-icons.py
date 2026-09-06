#!/usr/bin/env python3
"""Mint an accent-qualified, wallpaper-coloured Oxygen icon theme."""

from __future__ import annotations

import argparse
import colorsys
import fcntl
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image

SOURCE = Path("@oxygenIcons@") / "share" / "icons" / "oxygen"
RENDER_VERSION = "3"  # bump when the pixel transform changes


def theme_index(source, destination, name):
    text = (source / "index.theme").read_text()
    text = re.sub(r"^Name=.*$", "Name=" + name, text, count=1, flags=re.M)
    text = re.sub(r"^Inherits=.*$", "Inherits=oxygen", text, count=1, flags=re.M)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "index.theme").write_text(text)


def recolour(source, destination, accent):
    """Replace Oxygen's blue paint, retaining its shading and other inks."""
    accent_rgb = tuple(channel / 255.0 for channel in bytes.fromhex(accent))
    accent_hue, accent_saturation, _ = colorsys.rgb_to_hsv(*accent_rgb)

    def replace_blue(pixel):
        red, green, blue, alpha = pixel
        if alpha == 0:
            return pixel
        hue, saturation, value = colorsys.rgb_to_hsv(red / 255.0, green / 255.0,
                                                      blue / 255.0)
        # Oxygen's material colour is a blue band.  Keep black outlines,
        # white highlights and semantic warning/error colours untouched.
        if not (0.50 <= hue <= 0.72 and saturation >= 0.18):
            return pixel
        red, green, blue = colorsys.hsv_to_rgb(accent_hue, accent_saturation, value)
        return (round(red * 255), round(green * 255), round(blue * 255), alpha)

    for image_path in source.glob("base/**/*.png"):
        target = destination / image_path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(image_path) as image:
            rgba = image.convert("RGBA")
            tinted = Image.new("RGBA", rgba.size)
            tinted.putdata([replace_blue(pixel) for pixel in rgba.getdata()])
            tinted.save(target)


def activate(name):
    if kwriteconfig := shutil.which("kwriteconfig6"):
        subprocess.run([kwriteconfig, "--notify", "--file", "kdeglobals",
                        "--group", "Icons", "--key", "Theme", "--", name], check=False)
    if dbus_send := shutil.which("dbus-send"):
        subprocess.run([dbus_send, "--session", "--type=signal", "/KGlobalSettings",
                        "org.kde.KGlobalSettings.notifyChange", "int32:4", "int32:0"], check=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--accent", required=True, metavar="RRGGBB")
    parser.add_argument("--root", default=str(Path.home() / ".local/share/icons"))
    parser.add_argument("--no-activate", action="store_true")
    args = parser.parse_args()
    accent = args.accent.removeprefix("#").lower()
    if not re.fullmatch(r"[0-9a-f]{6}", accent):
        raise SystemExit("oxygen-live-icons: --accent must be six hex digits")
    if not SOURCE.is_dir():
        raise SystemExit("oxygen-live-icons: Oxygen icon source is missing")
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    state, lock = root / ".oxygen-live-state", root / ".oxygen-live.lock"
    with lock.open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        previous = state.read_text().strip().split() if state.exists() else []
        # KDE retains pixmaps by theme name.  The name therefore identifies
        # immutable pixels: both the transform version and the accent belong
        # in it, rather than reusing one of two mutable directories.
        name = "oxygen-live-v" + RENDER_VERSION + "-" + accent
        if previous != [RENDER_VERSION, accent] or not (root / name).is_dir():
            destination = root / name
            if destination.exists():
                shutil.rmtree(destination)
            theme_index(SOURCE, destination, "Oxygen Live " + accent)
            recolour(SOURCE, destination, accent)
            state.write_text(RENDER_VERSION + " " + accent + "\n")
        if not args.no_activate:
            activate(name)
    print(name)


if __name__ == "__main__":
    main()
