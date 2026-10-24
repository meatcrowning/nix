#!/usr/bin/env python3
"""Regenerate the local display font with fontTools; no runtime dependency.

Reads the same segment geometry as the Cairo readouts, without importing GTK.
"""
import ast
import math
from pathlib import Path
import unicodedata

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

ROOT = Path(__file__).resolve().parent.parent
constants = {}
for node in ast.parse((ROOT / 'rdsview.py').read_text()).body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in ('GLYPHS', 'SEGMENTS'):
                constants[target.id] = ast.literal_eval(node.value)


def glyph(char):
    pen = TTGlyphPen(None)

    def polygon(points):
        pen.moveTo(points[0])
        for point in points[1:]:
            pen.lineTo(point)
        pen.closePath()

    active = constants['GLYPHS'].get(char, constants['GLYPHS']['?'])
    if char in '.:,':
        active = ''
        for y in ((270, 550) if char == ':' else (130,)):
            polygon([(270, y - 28), (270, y + 28), (326, y + 28), (326, y - 28)])
    for index, (start, end) in enumerate(constants['SEGMENTS']):
        if chr(97 + index) not in active:
            continue
        x1, y1 = 70 + start[0] * 460, 830 - start[1] * 700
        x2, y2 = 70 + end[0] * 460, 830 - end[1] * 700
        length = math.hypot(x2 - x1, y2 - y1)
        dx, dy = (x2 - x1) / length * 32, (y2 - y1) / length * 32
        polygon([(x1 - dy, y1 + dx), (x2 - dy, y2 + dx),
                 (x2 + dy, y2 - dx), (x1 + dy, y1 - dx)])
    return pen.glyph()


chars = sorted(set(constants['GLYPHS']) | set('.:,'))
glyphs = {'.notdef': glyph('?')}
glyphs.update({f'cell{ord(c)}': glyph(c) for c in chars})
cmap = {}
for code in range(32, 384):
    text = unicodedata.normalize('NFKD', chr(code).upper())
    if text and text[0] in chars:
        cmap[code] = f'cell{ord(text[0])}'
for code, char in {0x2013: '-', 0x2014: '-', 0x2212: '-', 0xb7: '.',
                   0x2026: '.', 0x2019: "'"}.items():
    cmap[code] = f'cell{ord(char)}'
font = FontBuilder(1000, isTTF=True)
font.setupGlyphOrder(list(glyphs))
font.setupCharacterMap(cmap)
font.setupGlyf(glyphs)
font.setupHorizontalMetrics({name: (600, 60) for name in glyphs})
font.setupHorizontalHeader(ascent=900, descent=-100)
font.setupNameTable({'familyName': 'Tuner Segment', 'styleName': 'Regular',
                    'uniqueFontIdentifier': 'TunerSegment-Regular-1',
                    'fullName': 'Tuner Segment Regular', 'psName': 'TunerSegment-Regular'})
font.setupOS2(sTypoAscender=900, sTypoDescender=-100, usWinAscent=900, usWinDescent=100)
font.setupPost()
font.setupMaxp()
font.font['head'].created = font.font['head'].modified = 2082844800
font.save(ROOT / 'segment.ttf')
