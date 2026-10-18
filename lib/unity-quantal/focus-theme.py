"""Build immutable wallpaper-accent variants of Unity's native themes."""
import colorsys
import configparser
import fcntl
import os
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sys

from PIL import Image

HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
RGB = re.compile(r"rgba?\(\s*([\d.]+%?)\s*,\s*([\d.]+%?)\s*,\s*([\d.]+%?)(\s*,\s*[\d.]+)?\s*\)")


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


@lru_cache(maxsize=131072)
def recolor(rgb, target):
    h, s, v = colorsys.rgb_to_hsv(*(c / 255. for c in rgb))
    # Include pale highlights and brown shadows in orange icon gradients.
    if not (.02 <= h <= .14 and s > .15 and v > .05):
        return rgb
    th, ts, tv = colorsys.rgb_to_hsv(*(c / 255. for c in target))
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(th, min(1, ts * s / .71), min(1, tv * v / .94)))


def stylesheet(text, color):
    def replace(match):
        # SVG gradient references can have all-hex IDs; they are not colors.
        if re.search(r"(?:url\(\s*['\"]?|href=['\"])$", match.string[max(0, match.start() - 20):match.start()]):
            return match[0]
        digits = match[0][1:]
        if len(digits) == 3:
            digits = ''.join(c * 2 for c in digits)
        rgb = tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))
        return '#%02x%02x%02x' % recolor(rgb, color) + digits[6:]
    def replace_rgb(match):
        rgb = tuple(round(float(c[:-1]) * 2.55) if c.endswith('%') else round(float(c))
                    for c in match.groups()[:3])
        result = recolor(rgb, color)
        return ('rgba' if match[4] else 'rgb') + '(' + ','.join(map(str, result)) + (match[4] or '') + ')'
    text = RGB.sub(replace_rgb, HEX.sub(replace, text))
    for name, rgb in [('darkorange', (255, 140, 0)), ('orange', (255, 165, 0)),
                      ('orangered', (255, 69, 0)), ('coral', (255, 127, 80))]:
        text = re.sub(r'(?<=:)\s*' + name + r'(?=[;"\s}])',
                      '#%02x%02x%02x' % recolor(rgb, color), text, flags=re.I)
        text = re.sub(r'(?<==")' + name + r'(?=")',
                      '#%02x%02x%02x' % recolor(rgb, color), text, flags=re.I)
    return text


def asset(path, output, color):
    output.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in ('.css', '.rc', '.ini', '.xml', '.svg', '.xpm') or path.name == 'gtkrc':
        output.write_text(stylesheet(path.read_text(), color))
    elif path.suffix.lower() == '.png':
        with Image.open(path) as picture:
            picture = picture.convert('RGBA')
            picture.putdata([(*recolor(pixel[:3], color), pixel[3]) for pixel in picture.getdata()])
            picture.save(output, format='PNG')
    else:
        output.write_bytes(path.read_bytes())


def icon_roots(config, home):
    return [Path(home) / '.icons',
            Path(os.environ.get('XDG_DATA_HOME', str(Path(home) / '.local/share'))) / 'icons',
            Path(home) / '.local/share/icons',
            Path(config['runtime']) / 'usr/share/icons']


def build_icons(base, color, config, home):
    if not base or Path(base).name != base or base in ('.', '..'):
        raise ValueError('Invalid icon theme name')
    roots = icon_roots(config, home)
    exports = roots[1] / 'hicolor'
    revision = [(str(p.relative_to(exports)), p.stat().st_mtime_ns, p.stat().st_size)
                for p in sorted(exports.rglob('*')) if p.is_file()] if exports.is_dir() else []
    key = hashlib.sha256(repr((str(config['runtime']), color, base, revision, 3)).encode()).hexdigest()[:16]
    names = {}
    def derive(theme):
        if theme in names:
            return names[theme]
        sources = list(dict.fromkeys(root / theme for root in roots if (root / theme / 'index.theme').is_file()))
        if not sources:
            return theme
        name = 'Unity-Focus-Icons-' + theme + '-' + key
        names[theme] = name
        destination = Path(home) / '.icons' / name
        if (destination / '.complete').exists():
            return name
        index = configparser.ConfigParser(interpolation=None, strict=False)
        index.optionxform = str
        directories, inherited = [], []
        for source in sources:
            part = configparser.ConfigParser(interpolation=None, strict=False)
            part.optionxform = str
            part.read(source / 'index.theme')
            for section in part.sections():
                if not index.has_section(section):
                    index[section] = dict(part[section])
            directories += part.get('Icon Theme', 'Directories', fallback='').split(',')
            inherited += part.get('Icon Theme', 'Inherits', fallback='').split(',')
        index['Icon Theme']['Name'] = name
        index['Icon Theme']['Directories'] = ','.join(dict.fromkeys(d for d in directories if d))
        index['Icon Theme']['Inherits'] = ','.join(derive(p) for p in dict.fromkeys(inherited) if p and p != theme)
        destination.mkdir(parents=True, exist_ok=True)
        seen, resolved = set(), {}
        for source in sources:
            for folder, _, files in os.walk(source, followlinks=True):
                for filename in files:
                    path = Path(folder) / filename
                    relative = path.relative_to(source)
                    if relative in seen or path.suffix.lower() not in ('.png', '.svg', '.xpm') or not path.is_file():
                        continue
                    seen.add(relative)
                    output = destination / relative
                    output.parent.mkdir(parents=True, exist_ok=True)
                    origin = path.resolve()
                    if origin in resolved and not output.exists():
                        output.symlink_to(os.path.relpath(resolved[origin], output.parent))
                    else:
                        asset(path, output, color)
                        resolved[origin] = output
        with (destination / 'index.theme').open('w') as stream:
            index.write(stream, space_around_delimiters=False)
        (destination / '.complete').write_text(json.dumps({'base': theme}))
        return name
    return derive(base)


def build(base, wallpaper, config, home):
    if base not in ('Ambiance', 'Ambiance-Dark', 'Radiance'):
        raise ValueError('Dynamic focus color requires Ambiance, Ambiance Dark or Radiance')
    source = Path(config['runtime']) / 'usr/share/themes' / base
    native = Path(config['nativeFocusThemes']) / 'share/themes' / base
    color = accent(wallpaper)
    key = hashlib.sha256(repr((str(source), str(native), color, 3)).encode()).hexdigest()[:16]
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
                asset(path, output, color)
    (destination / '.complete').write_text('#%02x%02x%02x' % color)
    return name


if __name__ == '__main__':
    config = json.loads((Path(__file__).parent / 'config.json').read_text())
    cache = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache')))
    cache.mkdir(parents=True, exist_ok=True)
    # Wallpaper and theme notifications can overlap while the icons are built.
    with (cache / 'unity-focus-generation.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        name = build(sys.argv[1], sys.argv[2], config, Path.home())
        icons = build_icons(sys.argv[3], accent(sys.argv[2]), config, Path.home())
        print(json.dumps({'theme': name, 'icons': icons}))
