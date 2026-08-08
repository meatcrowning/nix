#!/usr/bin/env python3
"""Build "Phenex 6x8", a hand-authored connected-script (cursive) pixel
typeface, as a scalable outline TTF. Like Botis 4x6 (build-4x6.py) every pixel
of every glyph is invented here — no donor face — under the same explicit
override of the "do not invent a font" rule that let Botis exist.

    build-phenex-6x8.py <out.ttf>

The design intent (see docs/DESIGN.md for how the desktop consumes pixel
faces): a flowing, connected script face — the cursive counterpart to Botis's
blocky terminal look. Named for Phenex, the goetia's poet, in the same
demon-plus-grid pattern as Botis 4x6. Grid is 6 cells wide x 8 tall, baseline
on the bottom edge of row 5 (0-based, from the top):

    rows 0-1  ascenders, caps, i/j dots (hooked ascenders on b f h k l)
    rows 2-5  x-height (baseline under row 5)
    rows 6-7  descenders (f g j p q y — looped/curled tails)

WHAT MAKES IT CURSIVE — the connector convention. Advance is 6 px with ZERO
right side bearing, and every lowercase glyph carries an entry stub at
(row 5, col 0) and an exit stub at (row 5, col 5). Adjacent lowercase glyphs
therefore touch at the baseline: the exit of one is horizontally adjacent to
the entry of the next, so words read as one continuous pen stroke riding the
baseline, rising into each letterform. Capitals carry only the exit stub
(words start with caps; caps rarely follow a letter), and digits/punctuation
carry neither and keep column 5 empty, which restores the 1 px optical gap the
unconnected glyphs need.

Each glyph is authored as 8 rows of 6 pixels, '#' = ink. The hand-audited set
is all 95 printable ASCII plus the exact non-ASCII parity set Botis 4x6
carries (hardcoded desktop labels + the typographic punctuation that arrives
in foreign ID3/filename text) — see build-4x6.py for why each is load-bearing;
a glyph missing from the face makes its whole line take a taller fallback
ascent and clip.

OUTPUT IS A SCALABLE OUTLINE TTF, not a bitmap — same reason as Botis: a
non-scalable face is silently substituted by every text stack that asks
fontconfig for a scalable one (Pango titlebar, Quickshell GL scenegraph,
Context2D). Every authored pixel becomes a filled square contour.

The em is sized so the pixel grid stays crisp at the desktop default: UPM is
chosen so that at the panel's 15px pixelSize each authored pixel maps to an
exact 2x2 device-pixel block — the SAME 2px-per-pixel scale as Botis (the
ratio PX_UNITS/UPM = 2/15 is grid-height independent). The cell is therefore
16 device px tall at 15px pixelSize (8 rows x 2 px): taller than the em, which
is fine — every consumer measures the live face's cell (Theme.lineHeight /
DeskStyle.lineHeight), never the em size. See docs/DESIGN.md §2.1.
"""

import sys
from pathlib import Path

# --- the glyphs --------------------------------------------------------------
# key: codepoint; value: 8 rows, each 6 chars of '#'/'.' (row 0 = top,
# baseline under row 5). Lowercase: entry ink at (5,0), exit ink at (5,5).
G = {
0x20: ["......"]*8,                                                            # space
0x21: ["..#...","..#...","..#...","..#...","......","..#...","......","......"],  # !
0x22: [".#.#..",".#.#..","......","......","......","......","......","......"],  # "
0x23: ["......",".#.#..","#####.",".#.#..","#####.",".#.#..","......","......"],  # #
0x24: ["..#...",".####.","#.#...",".###..","..#.#.","####..","......","......"],  # $
0x25: ["##..#.","##.#..","...#..","..#...",".#.##.","#..##.","......","......"],  # %
0x26: [".##...","#..#..",".##...","#.#.#.","#..#..",".##.#.","......","......"],  # &
0x27: ["..#...","..#...","......","......","......","......","......","......"],  # '
0x28: ["...#..","..#...","..#...","..#...","..#...","...#..","......","......"],  # (
0x29: [".#....","..#...","..#...","..#...","..#...",".#....","......","......"],  # )
0x2a: ["......","#.#.#.",".###..","#.#.#.","......","......","......","......"],  # *
0x2b: ["......","......","..#...","#####.","..#...","......","......","......"],  # +
0x2c: ["......","......","......","......","......","..#...",".#....","......"],  # ,
0x2d: ["......","......","......","#####.","......","......","......","......"],  # -
0x2e: ["......","......","......","......","......","..#...","......","......"],  # .
0x2f: ["....#.","...#..","...#..","..#...",".#....","#.....","......","......"],  # /
0x30: [".###..","#...#.","#..##.","##..#.","#...#.",".###..","......","......"],  # 0 (slashed)
0x31: ["..#...",".##...","..#...","..#...","..#...",".###..","......","......"],  # 1
0x32: [".###..","#...#.","....#.","..##..",".#....","#####.","......","......"],  # 2
0x33: [".###..","#...#.","..##..","....#.","#...#.",".###..","......","......"],  # 3
0x34: ["...#..","..##..",".#.#..","#..#..","#####.","...#..","......","......"],  # 4
0x35: ["#####.","#.....","####..","....#.","#...#.",".###..","......","......"],  # 5
0x36: ["..##..",".#....","####..","#...#.","#...#.",".###..","......","......"],  # 6
0x37: ["#####.","....#.","...#..","..#...","..#...","..#...","......","......"],  # 7
0x38: [".###..","#...#.",".###..","#...#.","#...#.",".###..","......","......"],  # 8
0x39: [".###..","#...#.","#...#.",".####.","...#..",".##...","......","......"],  # 9
0x3a: ["......","......","......","..#...","......","..#...","......","......"],  # :
0x3b: ["......","......","......","..#...","......","..#...",".#....","......"],  # ;
0x3c: ["......","......","..##..","##....","..##..","......","......","......"],  # <
0x3d: ["......","......","#####.","......","#####.","......","......","......"],  # =
0x3e: ["......","......",".##...","...##.",".##...","......","......","......"],  # >
0x3f: [".###..","#...#.","...#..","..#...","......","..#...","......","......"],  # ?
0x40: [".###..","#...#.","#.###.","#.#.#.","#.###.",".##...","......","......"],  # @

# --- capitals: cursive-leaning caps, rows 0-5, exit stub at (5,5) ------------
0x41: ["..#...",".#.#..","#...#.","#####.","#...#.","#...##","......","......"],  # A
0x42: ["####..","#...#.","####..","#...#.","#...#.","####..","......","......"],  # B
0x43: [".###..","#...#.","#.....","#.....","#...#.",".###..","......","......"],  # C
0x44: ["####..","#...#.","#...#.","#...#.","#...#.","####..","......","......"],  # D
0x45: [".####.","#.....","###...","#.....","#.....",".#####","......","......"],  # E
0x46: ["#####.","#.....","###...","#.....","#.....","#.....","......","......"],  # F
0x47: [".###..","#...#.","#.....","#..##.","#...#.",".###..","......","......"],  # G
0x48: ["#...#.","#...#.","#####.","#...#.","#...#.","#...##","......","......"],  # H
0x49: [".###..","..#...","..#...","..#...","..#...",".###..","......","......"],  # I
0x4a: ["..###.","...#..","...#..","...#..","#..#..",".##...","......","......"],  # J
0x4b: ["#...#.","#..#..","###...","#..#..","#...#.","#...##","......","......"],  # K
0x4c: ["#.....","#.....","#.....","#.....","#.....","######","......","......"],  # L
0x4d: ["#...#.","##.##.","#.#.#.","#...#.","#...#.","#...##","......","......"],  # M
0x4e: ["#...#.","##..#.","#.#.#.","#..##.","#...#.","#...##","......","......"],  # N
0x4f: [".###..","#...#.","#...#.","#...#.","#...#.",".###..","......","......"],  # O
0x50: ["####..","#...#.","####..","#.....","#.....","#.....","......","......"],  # P
0x51: [".###..","#...#.","#...#.","#...#.","#..#..",".##.##","......","......"],  # Q
0x52: ["####..","#...#.","####..","#..#..","#...#.","#...##","......","......"],  # R
0x53: [".####.","#.....",".###..","....#.","#...#.",".###..","......","......"],  # S
0x54: ["#####.","..#...","..#...","..#...","..#...","..#...","......","......"],  # T
0x55: ["#...#.","#...#.","#...#.","#...#.","#...#.",".###..","......","......"],  # U
0x56: ["#...#.","#...#.","#...#.",".#.#..",".#.#..","..#...","......","......"],  # V
0x57: ["#...#.","#...#.","#...#.","#.#.#.","#.#.#.",".#.#..","......","......"],  # W
0x58: ["#...#.",".#.#..","..#...","..#...",".#.#..","#...##","......","......"],  # X
0x59: ["#...#.","#...#.",".#.#..","..#...","..#...","..#...","......","......"],  # Y
0x5a: ["#####.","...#..","..#...",".#....","#.....","######","......","......"],  # Z

0x5b: [".###..",".#....",".#....",".#....",".#....",".###..","......","......"],  # [
0x5c: ["#.....",".#....",".#....","..#...","...#..","....#.","......","......"],  # backslash
0x5d: [".###..","...#..","...#..","...#..","...#..",".###..","......","......"],  # ]
0x5e: ["..#...",".#.#..","......","......","......","......","......","......"],  # ^
0x5f: ["......","......","......","......","......","######","......","......"],  # _
0x60: [".#....","..#...","......","......","......","......","......","......"],  # `

# --- lowercase: the connected script. entry (5,0), exit (5,5), advance 6 -----
0x61: ["......","......",".####.","#...#.","#...#.","######","......","......"],  # a
0x62: [".##...",".#....",".#....",".####.",".#..#.","######","......","......"],  # b (hooked ascender, closed bowl)
0x63: ["......","......",".###..","#.....","#.....","######","......","......"],  # c
0x64: ["....#.","....#.",".####.","#...#.","#...#.","######","......","......"],  # d (plain tall stem)
0x65: ["......","......",".###..","####..","#.....","######","......","......"],  # e
0x66: ["..##..","..#...","..#...",".####.","..#...","######","..#...",".##..."],  # f (hook, bar, looped tail)
0x67: ["......","......",".####.","#...#.","#...#.","######","....#.","..###."],  # g (tail curls left)
0x68: [".##...",".#....",".#....",".####.",".#..#.","##..##","......","......"],  # h (open at baseline, vs b)
0x69: ["......","..#...","......","..#...","..#...","######","......","......"],  # i
0x6a: ["......","...#..","......","...#..","...#..","######","...#..",".##..."],  # j
0x6b: [".##...",".#....",".#....",".#.##.",".##...","##.###","......","......"],  # k
0x6c: [".##...",".#....",".#....",".#....",".#....","######","......","......"],  # l
0x6d: ["......","......","#####.","#.#.#.","#.#.#.","#.#.##","......","......"],  # m
0x6e: ["......","......",".####.",".#..#.",".#..#.","##..##","......","......"],  # n
0x6f: ["......","......","..##..",".#..#.",".#..#.","######","......","......"],  # o (narrow, vs a)
0x70: ["......","......",".####.",".#..#.",".#..#.","######",".#....",".#...."],  # p (a-bowl, left stem descends)
0x71: ["......","......",".####.","#...#.","#...#.","######","....#.","....##"],  # q (tail kicks right, vs g)
0x72: ["......","......",".####.",".#....",".#....","######","......","......"],  # r
0x73: ["......","......",".####.",".##...","...##.","######","......","......"],  # s
0x74: ["..#...",".####.","..#...","..#...","..#...","######","......","......"],  # t (plain ascender, high bar)
0x75: ["......","......","#...#.","#...#.","#...#.","######","......","......"],  # u
0x76: ["......","......","#...#.","#...#.",".#.#..","###.##","......","......"],  # v
0x77: ["......","......","#...#.","#.#.#.","#.#.#.","######","......","......"],  # w
0x78: ["......","......",".#..#.","..##..","..##..","##..##","......","......"],  # x
0x79: ["......","......","#...#.","#...#.","#...#.","######","....#.","..###."],  # y (u + g's tail)
0x7a: ["......","......",".####.","...#..","..#...","######","......","......"],  # z

0x7b: ["...##.","..#...",".##...","..#...","..#...","...##.","......","......"],  # {
0x7c: ["..#...","..#...","..#...","..#...","..#...","..#...","......","......"],  # |
0x7d: [".##...","...#..","...##.","...#..","...#..",".##...","......","......"],  # }
0x7e: ["......","......","......",".##.#.","#..#..","......","......","......"],  # ~

# --- non-ASCII glyphs the desktop actually RENDERS in the pixel font ----------
# The exact parity set Botis 4x6 carries — see build-4x6.py for the audit of
# why each is load-bearing (hardcoded labels + foreign-metadata punctuation;
# a missing glyph makes the whole line take a taller fallback and clip).
0x00b0: [".##...","#..#..",".##...","......","......","......","......","......"],  # ° temperature unit
0x00b7: ["......","......","......","..#...","......","......","......","......"],  # · separator
0x00d7: ["......","......",".#.#..","..#...",".#.#..","......","......","......"],  # × close buttons
0x2016: ["......",".#.#..",".#.#..",".#.#..",".#.#..",".#.#..","......","......"],  # ‖ pause
0x2039: ["......","......","..#...",".#....","..#...","......","......","......"],  # ‹ previous
0x203a: ["......","......","..#...","...#..","..#...","......","......","......"],  # › next
0x2191: ["......","..#...",".###..","..#...","..#...","..#...","......","......"],  # ↑ sort ascending
0x2193: ["......","..#...","..#...","..#...",".###..","..#...","......","......"],  # ↓ sort descending
0x2212: ["......","......","......","#####.","......","......","......","......"],  # − zoom out; bar aligns +,=
0x25a0: ["......","......",".####.",".####.",".####.",".####.","......","......"],  # ■ non-image placeholder
0x2588: ["######"]*8,                                                              # █ progress-bar fill
0x2591: ["#..#..","..#..#","#..#..","..#..#","#..#..","..#..#","#..#..","..#..#"],  # ░ progress-bar track
0x25b6: ["......","#.....","###...","#####.","###...","#.....","......","......"],  # ▶ play
0x2665: ["......",".#.#..","#####.","#####.",".###..","..#...","......","......"],  # ♥ favourite
0x266b: [".####.",".#..#.",".#..#.",".#..#.","##.##.","##.##.","......","......"],  # ♫ now-playing

# Typographic punctuation from FOREIGN text (ID3 tags, filenames) — ASCII-twin
# shapes, same rationale as Botis.
0x2018: ["..#...","..#...","......","......","......","......","......","......"],  # ' (= ')
0x2019: ["..#...","..#...","......","......","......","......","......","......"],  # ' (= ')
0x201c: [".#.#..",".#.#..","......","......","......","......","......","......"],  # " (= ")
0x201d: [".#.#..",".#.#..","......","......","......","......","......","......"],  # " (= ")
0x2013: ["......","......","......","#####.","......","......","......","......"],  # – (= -)
0x2014: ["......","......","......","#####.","......","......","......","......"],  # — (= -)
}

# --- metrics -----------------------------------------------------------------
W, H = 6, 8           # 6 wide, 8 tall  (the authored grid)
ADVANCE = 6           # ZERO right side bearing: exit stubs touch the next entry
ASCENT = 6            # rows 0..5 above/at baseline (baseline under row 5)
DESCENT = 2           # rows 6-7 below baseline
FAMILY = "Phenex 6x8"
FOUNDRY = "botis"

# Outline (scalable) metrics. One authored pixel is a PX_UNITS-square contour.
# The crispness constraint is the same as Botis's: at the panel's 15px
# pixelSize one authored pixel must be an exact 2x2 device-pixel block, i.e.
# PX_UNITS/UPM = 2/15 — which is independent of the grid height, so the same
# PX_UNITS = 100, UPM = 750 pair carries over. The 8-row cell is 800 units
# (16px at 15px pixelSize), deliberately taller than the em: consumers measure
# the live face's cell (Theme.lineHeight / DeskStyle.lineHeight), not the em.
PX_UNITS = 100
UPM = round(PX_UNITS * 15 / 2)       # 750
ASCENT_U = ASCENT * PX_UNITS         # 600 units above the baseline
DESCENT_U = DESCENT * PX_UNITS       # 200 units below the baseline
ADVANCE_U = ADVANCE * PX_UNITS       # 600 units


def pixel_square(pen, r, c):
    """Emit one authored pixel (row r from the top, col c) as a filled square
    contour. y is baseline-relative and up-positive: the cell spans ASCENT_U
    above the baseline down to -DESCENT_U below it."""
    x0 = c * PX_UNITS
    x1 = x0 + PX_UNITS
    y1 = ASCENT_U - r * PX_UNITS         # top edge of this row
    y0 = y1 - PX_UNITS                   # bottom edge
    pen.moveTo((x0, y0))
    pen.lineTo((x1, y0))
    pen.lineTo((x1, y1))
    pen.lineTo((x0, y1))
    pen.closePath()


def glyph_name(cp):
    return "space" if cp == 0x20 else f"uni{cp:04X}"


def build_ttf(out):
    """Build the scalable outline TTF: every '#' pixel becomes a PX_UNITS
    square. Abutting squares share edges of the same winding, so the rasteriser
    fills the union — no seams — while non-adjacent ink stays separate."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    cps = sorted(G)
    glyph_order = [".notdef"] + [glyph_name(cp) for cp in cps]

    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap({cp: glyph_name(cp) for cp in cps})

    glyphs = {}
    metrics = {}
    npen = TTGlyphPen(None)
    glyphs[".notdef"] = npen.glyph()
    metrics[".notdef"] = (ADVANCE_U, 0)
    for cp in cps:
        pen = TTGlyphPen(None)
        for r, row in enumerate(G[cp]):
            for c, ch in enumerate(row):
                if ch == "#":
                    pixel_square(pen, r, c)
        glyphs[glyph_name(cp)] = pen.glyph()
        # Mono: every glyph advances ADVANCE_U; LSB left at 0 (the grid origin).
        metrics[glyph_name(cp)] = (ADVANCE_U, 0)

    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASCENT_U, descent=-DESCENT_U)
    fb.setupNameTable({
        "familyName": FAMILY,
        "styleName": "Regular",
        "fullName": FAMILY,
        "psName": FAMILY.replace(" ", "") + "-Regular",
        "version": "1.0",
        "uniqueFontIdentifier": f"{FOUNDRY};{FAMILY};1.0",
    })
    fb.setupOS2(
        sTypoAscender=ASCENT_U, sTypoDescender=-DESCENT_U, sTypoLineGap=0,
        usWinAscent=ASCENT_U, usWinDescent=DESCENT_U,
    )
    fb.setupPost(isFixedPitch=1)
    fb.font["head"].lowestRecPPEM = 8
    fb.save(str(out))


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("Phenex6x8.ttf")
    # sanity: all 95 printable ASCII present, all rows W wide (authored)
    ascii_cps = [cp for cp in G if 0x20 <= cp <= 0x7E]
    assert len(ascii_cps) == 95, f"expected 95 printable ASCII, got {len(ascii_cps)}"
    for cp, rows in G.items():
        assert len(rows) == H, f"U+{cp:04X}: want {H} rows"
        for r in rows:
            assert len(r) == W and set(r) <= {'.', '#'}, f"U+{cp:04X}: bad row {r!r}"
    # sanity: every lowercase letter carries its connector stubs
    for cp in range(0x61, 0x7B):
        rows = G[cp]
        assert rows[5][0] == "#", f"{chr(cp)}: missing entry stub at (5,0)"
        assert rows[5][5] == "#", f"{chr(cp)}: missing exit stub at (5,5)"
    build_ttf(out)
    print(f"wrote {out}: {len(G)} glyphs, scalable outline, UPM {UPM}, "
          f"1px={PX_UNITS}u, advance {ADVANCE_U}, ascent {ASCENT_U} descent {DESCENT_U}")


if __name__ == "__main__":
    main()
