#!/usr/bin/env python3
"""Mint an accent-qualified, wallpaper-coloured Oxygen icon theme."""

from __future__ import annotations

import argparse
import colorsys
import fcntl
from functools import lru_cache
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

SOURCE = Path("@oxygenIcons@") / "share" / "icons" / "oxygen"
RENDER_VERSION = "6"  # bump when the pixel transform changes
VIVALDI_NAMES = ("vivaldi", "vivaldi-stable", "com.vivaldi.Vivaldi")
CODEX_NAMES = ("codex",)


def theme_index(source, destination, name):
    text = (source / "index.theme").read_text()
    text = re.sub(r"^Name=.*$", "Name=" + name, text, count=1, flags=re.M)
    text = re.sub(r"^Inherits=.*$", "Inherits=oxygen", text, count=1, flags=re.M)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "index.theme").write_text(text)


@lru_cache(maxsize=16)
def tint_table(accent):
    h, s, _ = colorsys.rgb_to_hsv(*(c / 255 for c in bytes.fromhex(accent)))
    # Retain the scalar transform's exact rounding, once per accent.
    return np.array([tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h, s, v / 255))
                     for v in range(256)], dtype=np.uint8)


def tint(image, accent, red_ink=False):
    """Vectorised colorsys transform; preserve alpha, shading and semantic inks."""
    pixels = np.array(image.convert("RGBA"))
    rgb = pixels[..., :3].astype(np.float64) / 255.0
    r, g, b = np.moveaxis(rgb, -1, 0)
    high, low = rgb.max(axis=-1), rgb.min(axis=-1)
    delta = high - low
    safe = np.where(delta == 0, 1, delta)
    rc, gc, bc = (high - r) / safe, (high - g) / safe, (high - b) / safe
    hue = (np.where(r == high, bc - gc,
                    np.where(g == high, 2 + rc - bc, 4 + gc - rc)) / 6) % 1
    saturation = delta / np.where(high == 0, 1, high)
    band = ((hue <= .08) | (hue >= .92)) if red_ink else ((hue >= .50) & (hue <= .72))
    mask = band & (saturation >= (.30 if red_ink else .18)) & (pixels[..., 3] != 0)
    value = pixels[..., :3].max(axis=-1)
    pixels[..., :3][mask] = tint_table(accent)[value[mask]]
    return Image.fromarray(pixels)


def recolour(source, destination, accent):
    for image_path in source.glob("base/**/*.png"):
        target = destination / image_path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(image_path) as image:
            tint(image, accent).save(target, compress_level=1)


def icon_data_roots():
    """Icon roots from both hosts, including Flatpak's exported app icons."""
    home = Path.home()
    roots = [Path(p) for p in __import__("os").environ.get(
        "XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if p]
    roots += [home / ".local/share", home / ".nix-profile/share",
              Path("/run/current-system/sw/share"),
              home / ".local/share/flatpak/exports/share",
              Path("/var/lib/flatpak/exports/share")]
    return list(dict.fromkeys(roots))


def recolour_vivaldi(destination, accent, data_roots=None):
    """Replace Vivaldi's red paint while retaining its white mark and shading."""
    roots = icon_data_roots() if data_roots is None else data_roots

    for size_dir in SOURCE.glob("base/*x*"):
        size = size_dir.name
        source = next((root / "icons/hicolor" / size / "apps" / (name + ".png")
                       for root in roots for name in VIVALDI_NAMES
                       if (root / "icons/hicolor" / size / "apps" /
                           (name + ".png")).is_file()), None)
        if source is None:
            continue
        with Image.open(source) as image:
            tinted = tint(image, accent, red_ink=True)
            target_dir = destination / "base" / size / "apps"
            target_dir.mkdir(parents=True, exist_ok=True)
            for name in VIVALDI_NAMES:
                tinted.save(target_dir / (name + ".png"), compress_level=1)


def recolour_codex(destination, accent, data_roots=None):
    """Replace Codex's cobalt enamel while retaining its silver and shading."""
    roots = icon_data_roots() if data_roots is None else data_roots

    for size_dir in SOURCE.glob("base/*x*"):
        size = size_dir.name
        source = next((root / "icons/hicolor" / size / "apps" / (name + ".png")
                       for root in roots for name in CODEX_NAMES
                       if (root / "icons/hicolor" / size / "apps" /
                           (name + ".png")).is_file()), None)
        if source is None:
            continue
        with Image.open(source) as image:
            tinted = tint(image, accent, red_ink=False)
            target_dir = destination / "base" / size / "apps"
            target_dir.mkdir(parents=True, exist_ok=True)
            for name in CODEX_NAMES:
                tinted.save(target_dir / (name + ".png"), compress_level=1)


PLASMA_CHANGEICONS = Path("@plasmaChangeIcons@")


def activate(name):
    # KIconLoader's shared pixmap cache (~/.cache/icon-cache.kcache) is keyed
    # by icon name, not theme, so open KDE programs keep drawing the previous
    # accent's pixmaps after a plain config write. plasma-changeicons is the
    # System Settings path: it writes the key, deletes that cache and emits
    # KIconLoader's change to every process [top, 2026-11-14].
    if PLASMA_CHANGEICONS.is_file():
        done = subprocess.run([str(PLASMA_CHANGEICONS), name], check=False,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if done.returncode == 0:
            refresh_decorations()
            return
    if kwriteconfig := shutil.which("kwriteconfig6"):
        subprocess.run([kwriteconfig, "--notify", "--file", "kdeglobals",
                        "--group", "Icons", "--key", "Theme", "--", name], check=False)
    if dbus_send := shutil.which("dbus-send"):
        subprocess.run([dbus_send, "--session", "--type=signal", "/KGlobalSettings",
                        "org.kde.KGlobalSettings.notifyChange", "int32:4", "int32:0"], check=False)
    refresh_decorations()


def refresh_decorations():
    # KWin's decoration keeps a separate QIcon cache.  The color-scheme
    # transaction already reconfigures it, but the icon theme finishes after
    # that transaction unless we ask it to re-read here.
    if busctl := shutil.which("busctl"):
        subprocess.run([busctl, "--user", "call", "org.kde.KWin", "/KWin",
                        "org.kde.KWin", "reconfigure"], check=False)
    if hyprctl := shutil.which("hyprctl"):
        subprocess.run([hyprctl, "eval", "hl.plugin.hyprvtb.refresh_icons()"],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def superseded(accent):
    """Newer accent published by wal-set.sh's theme-target, or None."""
    target = Path.home() / ".cache/wal/theme-target"
    try:
        lines = target.read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("icons="):
            wanted = line.removeprefix("icons=").strip().lower()
            return wanted if wanted and wanted != accent else None
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--accent", required=True, metavar="RRGGBB")
    parser.add_argument("--root", default=str(Path.home() / ".local/share/icons"))
    parser.add_argument("--no-activate", action="store_true")
    parser.add_argument("--activate-only", action="store_true")
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
        if not args.no_activate and (newer := superseded(accent)):
            print(f"oxygen-live-icons: {accent} superseded by {newer}, skipping")
            return
        # KDE retains pixmaps by theme name.  The name therefore identifies
        # immutable pixels: both the transform version and the accent belong
        # in it, rather than reusing one of two mutable directories.
        name = "oxygen-live-v" + RENDER_VERSION + "-" + accent
        destination = root / name
        ready = destination / ".complete"
        if args.activate_only and not ready.is_file():
            raise SystemExit("oxygen-live-icons: prepared icon theme is unavailable")
        if not ready.is_file():
            # Publish only a complete tree. A killed render cannot become a
            # cache hit, and A -> B -> A reuses A without rewriting its pixels.
            with tempfile.TemporaryDirectory(prefix=".oxygen-render-", dir=root) as work:
                staging = Path(work) / name
                theme_index(SOURCE, staging, "Oxygen Live " + accent)
                recolour(SOURCE, staging, accent)
                recolour_vivaldi(staging, accent)
                recolour_codex(staging, accent)
                (staging / ".complete").write_text(RENDER_VERSION + " " + accent + "\n")
                if destination.exists():
                    shutil.rmtree(destination)
                staging.rename(destination)
        state.write_text(RENDER_VERSION + " " + accent + "\n")
        # A newer pick may have landed while the theme was rendering.
        if not args.no_activate and (newer := superseded(accent)):
            print(f"oxygen-live-icons: {accent} superseded by {newer}, not activating")
            return
        if not args.no_activate:
            activate(name)
    print(name)


if __name__ == "__main__":
    main()
