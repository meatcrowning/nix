"""Use real game artwork for Steam's running-game menu image slot."""
from pathlib import Path


def complete(game, assets, directory):
    from PIL import Image

    directory = Path(directory)
    # Steam calls the menu slot a logo, but the desktop uses a wide artwork
    # banner there. Keep the original image's composition and aspect ratio.
    curated = [directory / f'{name}.{ext}'
               for name in ('header-curated', 'hero-curated')
               for ext in ('png', 'jpg', 'webp')]
    banner = next((path for path in curated if path.is_file()), None)
    banner = banner or assets.get('') or assets.get('_hero')
    if banner is None:
        gameplay = directory / 'hero-gameplay.png'
        banner = gameplay if gameplay.is_file() else None
    if banner is None:
        return assets  # Report missing art; never disguise title text as artwork.
    image_path = directory / 'menu-banner.png'
    with Image.open(banner) as image:
        image.convert('RGB').save(image_path)
    assets['_logo'] = image_path
    assets.setdefault('', image_path)
    return assets
