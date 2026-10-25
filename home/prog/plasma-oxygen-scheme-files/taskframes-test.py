#!/usr/bin/env python3
"""Render task states with synthetic palettes, without a desktop or windows."""
import gzip
import itertools
from pathlib import Path
import sys
import tempfile
import xml.etree.ElementTree as ET

from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
import taskframes

app = QGuiApplication([])
assert app.platformName() == 'offscreen'
with tempfile.TemporaryDirectory(prefix='oxygen-taskframes-') as tmp:
    output = str(Path(tmp) / 'tasks.svgz')
    taskframes.build(sys.argv[1], output)
    root = ET.fromstring(gzip.decompress(Path(output).read_bytes()))
    ids = [e.get('id') for e in root.iter() if e.get('id')]
    assert len(ids) == len(set(ids)), 'duplicate SVG ids'
    style = next(e for e in root.iter() if e.tag.endswith('}style'))

    def render(palette):
        style.text = '\n'.join('.ColorScheme-%s { color:%s; stop-color:%s; }' % (k, v, v)
                               for k, v in palette.items())
        renderer = QSvgRenderer(QByteArray(ET.tostring(root)))
        assert renderer.isValid()
        colors = {}
        for state in ('normal', 'focus', 'minimized'):
            for hover in ('', '-hover'):
                prefix = state + hover
                for part in taskframes.SLICES:
                    assert renderer.elementExists(prefix + '-' + part)
                    assert renderer.boundsOnElement(prefix + '-' + part) == renderer.boundsOnElement('normal-' + part)
                image = QImage(40, 40, QImage.Format_ARGB32_Premultiplied)
                image.fill(0)
                painter = QPainter(image)
                renderer.render(painter, prefix + '-center', QRectF(0, 0, 40, 40))
                painter.end()
                colors[prefix] = image.pixelColor(20, 20).getRgb()
        return colors

    for bg, button, highlight, hover in (('#22310f', '#3d492e', '#579a00', '#72cb00'),
                                        ('#e9edf2', '#fafafa', '#2864b4', '#82b4ef')):
        palette = dict(Background=bg, ButtonBackground=button, Highlight=highlight,
                       ButtonHover=hover, NeutralText='#b08030')
        colors = render(palette)
        for suffix in ('', '-hover'):
            for a, b in itertools.combinations(('normal', 'focus', 'minimized'), 2):
                assert sum(abs(x-y) for x,y in zip(colors[a+suffix], colors[b+suffix])) > 45, colors
        assert colors['minimized'][3] < 180 < colors['normal'][3]
        changed = render(dict(palette, Highlight='#c04090'))
        assert colors['focus'] != changed['focus']
        assert colors['normal'] == changed['normal']
        assert colors['minimized'] == changed['minimized']
print('PASS: task-state geometry, unique ids, dark/light contrast and live palette roles')
