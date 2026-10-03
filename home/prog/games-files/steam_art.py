"""Complete shortcut artwork without depending on a game's Steam store listing."""
from pathlib import Path


def complete(game, assets, directory):
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    directory = Path(directory)
    # Steam's running-game menu requires a logo even if the shortcut already
    # has a portrait and hero. Its image component has no title-text fallback.
    for suffix, name in [('_logo', 'logo'), ('', 'header')]:
        if suffix in assets:
            continue
        for extension in ('png', 'jpg'):
            curated = directory / f'{name}-curated.{extension}'
            if curated.is_file():
                assets[suffix] = curated
                break
        if suffix in assets:
            continue
        canvas = Image.new('RGBA', (920, 300 if suffix else 430),
                           (0, 0, 0, 0) if suffix else (18, 21, 27, 255))
        draw = ImageDraw.Draw(canvas)
        left = 24
        if not suffix and assets.get('p'):
            with Image.open(assets['p']) as source:
                cover = ImageOps.contain(source.convert('RGBA'), (260, 382))
            canvas.alpha_composite(cover, (24, (430 - cover.height) // 2))
            left = 310
        width = canvas.width - left - 24
        for size in range(68, 15, -2):
            font = ImageFont.load_default(size=size)
            lines = ['']
            for word in game['name'].split():
                candidate = (lines[-1] + ' ' + word).strip()
                if draw.textlength(candidate, font=font) > width and lines[-1]:
                    lines.append(word)
                else:
                    lines[-1] = candidate
            text = '\n'.join(lines)
            box = draw.multiline_textbbox((0, 0), text, font=font, spacing=10)
            if box[2] - box[0] <= width and box[3] - box[1] <= canvas.height - 48:
                break
        draw.multiline_text((left, (canvas.height - (box[3] - box[1])) // 2 - box[1]),
                            text, font=font, fill='white', spacing=10)
        path = directory / f'{name}-fallback.png'
        canvas.save(path)
        assets[suffix] = path
    return assets
