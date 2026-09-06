#!/usr/bin/env python3
"""Mint a two-slot, wallpaper-coloured Oxygen icon theme."""

from __future__ import annotations

import argparse
import fcntl
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image

SOURCE = Path("@oxygenIcons@") / "share" / "icons" / "oxygen"


def theme_index(source, destination, name):
    text = (source / "index.theme").read_text()
    text = re.sub(r"^Name=.*$", "Name=" + name, text, count=1, flags=re.M)
    text = re.sub(r"^Inherits=.*$", "Inherits=oxygen", text, count=1, flags=re.M)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "index.theme").write_text(text)


def recolour(source, destination, accent):
    colour = tuple(bytes.fromhex(accent))
    for image_path in source.glob("base/**/*.png"):
        target = destination / image_path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(image_path) as image:
            alpha = image.convert("RGBA").getchannel("A")
            tinted = Image.new("RGBA", image.size, colour + (0,))
            tinted.putalpha(alpha)
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
        if len(previous) == 2 and previous[0] == accent:
            slot = previous[1]
        else:
            slot = "1" if previous[-1:] == ["0"] else "0"
            destination = root / ("oxygen-live-" + slot)
            if destination.exists():
                shutil.rmtree(destination)
            theme_index(SOURCE, destination, "Oxygen Live " + slot)
            recolour(SOURCE, destination, accent)
            state.write_text(accent + " " + slot + "\n")
        name = "oxygen-live-" + slot
        if not args.no_activate:
            activate(name)
    print(name)


if __name__ == "__main__":
    main()
