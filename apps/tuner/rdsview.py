"""Fourteen-segment cells: the glyph table and how one cell is drawn.

tools/build-segment-font.py reads GLYPHS and SEGMENTS from this file, so
segment.ttf and the drawn display share one geometry.
"""

import unicodedata

from faceplate import GHOST, glow

# a..h are the perimeter/middle bars; i..n are diagonals and centre uprights.
SEGMENTS = (
    ((.12, .04), (.88, .04)), ((.95, .10), (.95, .43)),
    ((.95, .57), (.95, .90)), ((.12, .96), (.88, .96)),
    ((.05, .57), (.05, .90)), ((.05, .10), (.05, .43)),
    ((.12, .50), (.43, .50)), ((.57, .50), (.88, .50)),
    ((.15, .12), (.43, .42)), ((.50, .10), (.50, .42)),
    ((.85, .12), (.57, .42)), ((.15, .88), (.43, .58)),
    ((.50, .58), (.50, .90)), ((.85, .88), (.57, .58)),
)
GLYPHS = {
    '0': 'abcdef', '1': 'bc', '2': 'abdegh', '3': 'abcdgh', '4': 'bcfgh',
    '5': 'acdfgh', '6': 'acdefgh', '7': 'abc', '8': 'abcdefgh', '9': 'abcdfgh',
    'A': 'abcefgh', 'B': 'abcdhjm', 'C': 'adef', 'D': 'abcdjm',
    'E': 'adefgh', 'F': 'aefgh', 'G': 'acdefh', 'H': 'bcefgh',
    'I': 'adjm', 'J': 'bcde', 'K': 'efkn', 'L': 'def', 'M': 'bcefik',
    'N': 'bcefin', 'O': 'abcdef', 'P': 'abefgh', 'Q': 'abcdefn',
    'R': 'abefghn', 'S': 'acdfgh', 'T': 'ajm', 'U': 'bcdef',
    'V': 'efkl', 'W': 'bcefln', 'X': 'ikln', 'Y': 'ikm', 'Z': 'adkl',
    '-': 'gh', '_': 'd', '/': 'kl', '\\': 'in', '+': 'ghjm',
    '=': 'dgh', '?': 'abhm', ' ': '', '[': 'adef', ']': 'abcd',
    '(': 'ef', ')': 'bc', "'": 'j', '"': 'bj', '!': 'jm',
}


# A cell's three uprights, left to right, each as (lower, upper) segments:
# meters and the analyzer light these, so a bargraph is made of characters.
UPRIGHTS = (('e', 'f'), ('m', 'j'), ('c', 'b'))
ALL = 'abcdefghijklmn'


def display_text(text):
    text = text.replace('—', '-').replace('–', '-').replace('’', "'").replace('·', ' ')
    return ''.join(c for c in unicodedata.normalize('NFKD', text.upper())
                   if not unicodedata.combining(c))


def segments(char):
    return '' if char in '.:,' else GLYPHS.get(char, GLYPHS['?'])


def stroke_width(h):
    return max(1.1, h * .09)  # segment.ttf's stroke, so drawn and typeset text match


def add_segments(cr, active, x, y, w, h):
    """Append the named segments of one cell to the current path."""
    for index, (start, end) in enumerate(SEGMENTS):
        if chr(ord('a') + index) in active:
            cr.move_to(x + start[0] * w, y + start[1] * h)
            cr.line_to(x + end[0] * w, y + end[1] * h)


def add_dots(cr, char, x, y, w, h):
    """Append the decimal point or colon of one cell, as closed sub-paths."""
    for dy in ((.32, .72) if char == ':' else (.92,) if char in '.,' else ()):
        cr.new_sub_path()
        cr.arc(x + w * .5, y + h * dy, max(1, h * .055), 0, 6.284)


def glyph(cr, char, x, y, w, h, alpha=1.0):
    """One cell on its own: unlit segments in charcoal, lit ones glowing."""
    active = segments(char)
    cr.set_line_width(stroke_width(h))
    cr.set_source_rgb(*GHOST)
    add_segments(cr, ''.join(c for c in ALL if c not in active), x, y, w, h)
    cr.stroke()
    if active:
        add_segments(cr, active, x, y, w, h)
        glow(cr, stroke_width(h), alpha=alpha)
    if char in '.:,':
        add_dots(cr, char, x, y, w, h)
        glow(cr, 1, fill=True, alpha=alpha)
