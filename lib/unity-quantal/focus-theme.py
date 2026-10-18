"""Build immutable wallpaper-accent variants of Unity's native themes."""
import colorsys
import hashlib
import json
from pathlib import Path
import re
import sys

from PIL import Image

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def accent(path):
    with Image.open(path) as image:
        image.thumbnail((96, 96))
        pixels = list(image.convert("RGBA").getdata())
    bins = {}
    for r, g, b, a in pixels:
        h, s, v = colorsys.rgb_to_hsv(r / 255., g / 255., b / 255.)
        if a < 128 or s < .18 or v < .15:
            continue
        bucket = int(h * 24) % 24
        weight = s * v
        total, red, green, blue = bins.get(bucket, (0, 0, 0, 0))
        bins[bucket] = (total + weight, red + r * weight, green + g * weight, blue + b * weight)
    if not bins:
        return (112, 112, 112)
    total, r, g, b = max(bins.values())
    h, s, v = colorsys.rgb_to_hsv(r / total / 255, g / total / 255, b / total / 255)
    rgb = colorsys.hsv_to_rgb(h, min(.8, max(.45, s)), min(.78, max(.48, v)))
    # White selected text must remain legible, including on yellow wallpapers.
    def luminance(values):
        linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in values]
        return sum(c * w for c, w in zip(linear, (.2126, .7152, .0722)))
    while luminance(rgb) > .183:
        rgb = tuple(c * .97 for c in rgb)
    return tuple(round(c * 255) for c in rgb)


def recolor(rgb, target):
    h, s, v = colorsys.rgb_to_hsv(*(c / 255. for c in rgb))
    # Ubuntu's orange accents only: preserve warning reds, greys and artwork.
    if not (.025 <= h <= .105 and s > .45 and v > .35):
        return rgb
    th, ts, tv = colorsys.rgb_to_hsv(*(c / 255. for c in target))
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(th, ts, min(1, tv * v / .94)))


def stylesheet(text, color):
    def replace(match):
        rgb = tuple(int(match[0][i:i + 2], 16) for i in (1, 3, 5))
        return '#%02x%02x%02x' % recolor(rgb, color)
    return HEX.sub(replace, text)


def build(base, wallpaper, config, home):
    if base not in ('Ambiance', 'Ambiance-Dark', 'Radiance'):
        raise ValueError('Dynamic focus color requires Ambiance, Ambiance Dark or Radiance')
    source = Path(config['runtime']) / 'usr/share/themes' / base
    native = Path(config['nativeFocusThemes']) / 'share/themes' / base
    color = accent(wallpaper)
    key = hashlib.sha256(repr((str(source), str(native), color, 1)).encode()).hexdigest()[:16]
    name = 'Unity-Focus-' + base + '-' + key
    destination = Path(home) / '.themes' / name
    if (destination / '.complete').exists():
        return name
    destination.mkdir(parents=True, exist_ok=True)
    for root, parts in [(source, ('gtk-2.0', 'gtk-3.0', 'metacity-1', 'unity')),
                        (native, ('gtk-3.20',))]:
        for part in parts:
            for path in (root / part).rglob('*'):
                if not path.is_file():
                    continue
                output = destination / path.relative_to(root)
                output.parent.mkdir(parents=True, exist_ok=True)
                if path.suffix in ('.css', '.rc', '.ini', '.xml', '.svg') or path.name == 'gtkrc':
                    output.write_text(stylesheet(path.read_text(), color))
                elif path.suffix == '.png':
                    with Image.open(path) as image:
                        image = image.convert('RGBA')
                        image.putdata([(*recolor(pixel[:3], color), pixel[3]) for pixel in image.getdata()])
                        image.save(output)
                else:
                    output.write_bytes(path.read_bytes())
    (destination / '.complete').write_text('#%02x%02x%02x' % color)
    return name


if __name__ == '__main__':
    config = json.loads((Path(__file__).parent / 'config.json').read_text())
    print(build(sys.argv[1], sys.argv[2], config, Path.home()))
