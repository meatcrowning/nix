"""Derive Ambiance Dark: the original Ambiance theme with only its colours changed.

Light greys in stylesheets and widget images are mapped onto a palette just
below Ambiance's own dark chrome (its menubar, toolbar, and panel colour). Accents, dark greys, geometry,
gradients, and image shapes stay as Ubuntu shipped them.
"""

import colorsys
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

PALETTE = {
    "bg_color": "#33322f", "fg_color": "#dfdbd2", "base_color": "#282725",
    "text_color": "#e8e5de", "selected_bg_color": "#f07746", "selected_fg_color": "#ffffff",
    "tooltip_bg_color": "#000000", "tooltip_fg_color": "#ffffff",
}
# Colours already meant for Ambiance's dark surfaces (menubars, toolbars,
# tooltips, overlays) are kept as shipped.
KEEP = re.compile(r"dark|tooltip|osd")
# Ambiance's dark grey is slightly warm; mapped greys keep that tint.
WARM = (1.0, 0.983, 0.917)


def remap(r, g, b):
    """Return the dark-mode colour for one 0-255 RGB triple."""
    chroma = max(r, g, b) - min(r, g, b)
    light = (max(r, g, b) + min(r, g, b)) / 510
    if light < 0.5 or chroma > 60:
        return r, g, b
    # Linear lightness flip: #f2f1f0 -> bg_color and #ffffff -> base_color,
    # one step below the shipped dark chrome so menubars and toolbars still stand out.
    target = 0.877 - 0.727 * light
    grey = [target * 255 * w for w in WARM]
    scale = target * 255 * 3 / sum(grey)
    grey = [min(255, round(v * scale)) for v in grey]
    # Fade the remap out for tinted pixels, so accents keep their hue.
    keep = max(0.0, (chroma - 20) / 40)
    return tuple(round(new * (1 - keep) + old * keep) for new, old in zip(grey, (r, g, b)))


def hex_colour(match):
    text = match.group(0)
    digits = text[1:]
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    r, g, b = (int(digits[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % remap(r, g, b)


HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def scheme(match):
    entries = dict(item.split(":", 1) for item in match.group(1).split("\\n") if ":" in item)
    entries.update({key: value for key, value in PALETTE.items() if key in entries})
    return 'gtk-color-scheme = "' + "\\n".join(f"{k}:{v}" for k, v in entries.items()) + '"'


def stylesheet(path):
    text = path.read_text()
    text = re.sub(r'gtk-color-scheme\s*=\s*"([^"]*)"', scheme, text)
    lines = []
    for line in text.splitlines(keepends=True):
        define = re.match(r"(\s*@define-color\s+)(\w+)(\s+)[^;]*;", line)
        if define and define.group(2) in PALETTE:
            line = f"{define.group(1)}{define.group(2)}{define.group(3)}{PALETTE[define.group(2)]};\n"
        elif define and KEEP.search(define.group(2)):
            pass
        elif "gtk-color-scheme" not in line and not line.lstrip().startswith(("/*", "#")):
            line = HEX.sub(hex_colour, line)
        lines.append(line)
    path.write_text("".join(lines))


def image(path):
    picture = Image.open(path)
    mode = picture.mode
    picture = picture.convert("RGBA")
    pixels = picture.load()
    for y in range(picture.height):
        for x in range(picture.width):
            r, g, b, a = pixels[x, y]
            if a:
                pixels[x, y] = (*remap(r, g, b), a)
    if mode not in ("RGBA", "LA"):
        picture = picture.convert(mode) if mode != "P" else picture
    picture.save(path)


def artwork(path):
    """Lighten dark grey lettering drawn for light windows, such as the Details logo."""
    if path.is_symlink():
        target = path.resolve()
        path.unlink()
        shutil.copyfile(target, path)
    path.chmod(0o644)
    picture = Image.open(path).convert("RGBA")
    pixels = picture.load()
    light = tuple(int(PALETTE["fg_color"][i:i + 2], 16) for i in (1, 3, 5))
    for y in range(picture.height):
        for x in range(picture.width):
            r, g, b, a = pixels[x, y]
            if a and max(r, g, b) - min(r, g, b) < 20 and max(r, g, b) < 128:
                pixels[x, y] = (*light, a)
    picture.save(path)


def main(source, destination, *artworks):
    source, destination = Path(source), Path(destination)
    shutil.copytree(source, destination, symlinks=False)
    destination.chmod(0o755)
    for path in destination.rglob("*"):
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() else 0o644)
    for part in ["gtk-2.0", "gtk-3.0"]:
        for path in (destination / part).rglob("*"):
            if path.suffix in (".css", ".rc", ".ini") or path.name == "gtkrc":
                stylesheet(path)
            elif path.suffix == ".png":
                image(path)
    index = destination / "index.theme"
    index.write_text(index.read_text().replace("Name=Ambiance", "Name=Ambiance Dark"))
    for path in artworks:
        artwork(Path(path))


if __name__ == "__main__":
    main(*sys.argv[1:])
