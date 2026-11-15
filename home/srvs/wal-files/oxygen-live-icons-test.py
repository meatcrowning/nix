#!/usr/bin/env python3
"""Isolated pixel equivalence and publication/cache regression checks."""
import colorsys
import importlib.util
from pathlib import Path
import tempfile
from unittest.mock import patch

import numpy as np
from PIL import Image

spec = importlib.util.spec_from_file_location('icons', Path(__file__).with_name('oxygen-live-icons.py'))
icons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(icons)


def scalar(pixel, accent, red_ink):
    r, g, b, a = map(int, pixel)
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    band = (h <= .08 or h >= .92) if red_ink else (.50 <= h <= .72)
    if not a or not band or s < (.30 if red_ink else .18):
        return r, g, b, a
    ah, ass, _ = colorsys.rgb_to_hsv(*(c / 255 for c in bytes.fromhex(accent)))
    return (*[round(c * 255) for c in colorsys.hsv_to_rgb(ah, ass, v)], a)


def main():
    rng = np.random.default_rng(42)
    pixels = rng.integers(0, 256, (256, 256, 4), dtype=np.uint8)
    pixels[0, :, 3] = 0
    pixels[1, :, :3] = np.arange(256, dtype=np.uint8)[:, None]
    for accent in ('a19beb', 'ff0000', '000000', 'ffffff', '12abcd'):
        for red in (False, True):
            actual = np.asarray(icons.tint(Image.fromarray(pixels), accent, red))
            expected = np.array([scalar(p, accent, red) for p in pixels.reshape(-1, 4)],
                                dtype=np.uint8).reshape(pixels.shape)
            np.testing.assert_array_equal(actual, expected)
    with tempfile.TemporaryDirectory() as work:
        root = Path(work)
        source = root / 'source'
        source.mkdir()
        (source / 'index.theme').write_text('[Icon Theme]\nName=Oxygen\nInherits=hicolor\n')
        image = source / 'base/16x16/apps/test.png'
        image.parent.mkdir(parents=True)
        Image.new('RGBA', (16, 16), (10, 40, 200, 255)).save(image)
        output = root / 'output'

        def render(accent):
            with patch('sys.argv', ['icons', '--accent', accent, '--root', str(output)]):
                icons.main()

        with patch.object(icons, 'SOURCE', source), \
                patch.object(icons, 'superseded', return_value=None), \
                patch.object(icons, 'icon_data_roots', return_value=[]), \
                patch.object(icons, 'activate') as activate:
            render('a19beb')
            theme = output / ('oxygen-live-v' + icons.RENDER_VERSION + '-a19beb')
            before = (theme / 'base/16x16/apps/test.png').stat().st_mtime_ns
            render('ff0000')
            with patch.object(icons, 'recolour', side_effect=AssertionError('cache miss')):
                render('a19beb')
            assert (theme / 'base/16x16/apps/test.png').stat().st_mtime_ns == before
            assert activate.call_count == 3
            with patch.object(icons, 'recolour', side_effect=RuntimeError('interrupted')):
                try:
                    render('00ff00')
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('failure swallowed')
            assert activate.call_count == 3
            assert not (output / ('oxygen-live-v' + icons.RENDER_VERSION + '-00ff00')).exists()
            assert not list(output.glob('.oxygen-render-*'))
            with patch.object(icons, 'superseded', side_effect=[None, 'ffffff']):
                render('00ff00')
            assert activate.call_count == 3, 'superseded job activated'
    print('pixel equivalence, A/B/A cache reuse, failed publication, supersession: OK')


if __name__ == '__main__':
    main()
