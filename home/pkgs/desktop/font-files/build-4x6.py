#!/usr/bin/env python3
"""Build "Botis 4x6", a hand-authored 4-wide blocky pixel typeface, as a BDF
(and, from the derivation, a PCF). The whole of it — every pixel of every glyph
— is invented here: there is no donor face, no 4x4 pixel font exists on this
system to copy from, and the user explicitly overrode the "do not invent a
font" rule for this one face so it exists at all.

    build-4x6.py <out.ttf>

The design intent (see docs/DESIGN.md for how the desktop consumes pixel
faces): a square-ish, heavy, blocky 4-wide terminal face matching the style of
the specimen the user pointed at (blocky, thick, low-res LCD/tartaruga look).
Grid is 4 cells wide x 6 tall, baseline on row 4 (0-based, from the top), so:

    row 0   cap height / ascenders
    rows 1-4  x-height (baseline on row 4)
    row 5   descenders (g j p q y)

Ascent 5, descent 1 -> 6 px tall, matching the specimen's near-square cells.
Advance is 5 px (1 px right side bearing) so 4-wide strokes do not collide.

Each glyph is authored as 6 rows of 4 pixels, '#' = ink. Capital and lowercase
are deliberately drawn as distinct shapes (lowercase is x-height, caps full
height) so the face carries real case.

Hand-audited character set: all 95 printable ASCII (U+0020..U+007E), plus the
non-ASCII glyphs the desktop actually draws in this face as hardcoded labels
(see the block after the ASCII table).

OUTPUT IS A SCALABLE OUTLINE TTF, not a bitmap. Every authored pixel becomes a
filled square contour, so the face is a normal scalable font that any renderer
can rasterise. This is deliberate and load-bearing: as a non-scalable BDF the
face was SILENTLY SUBSTITUTED by every text stack that asks fontconfig for a
scalable face — proven, `fc-match "Botis 4x6:scalable=true"` returned Noto Sans,
and Pango (the hyprvtb titlebar) and the Quickshell GL scenegraph both dropped
Botis for a generic sans. An outline face is matched and drawn by all of them.

The em is sized so the pixel grid stays crisp at the desktop default. UPM (below)
is chosen so that at the panel's 15px pixelSize each authored pixel maps to an
exact integer device-pixel block (2x2 at 15px) — pixel-identical to the old
8x12 BDF — while the font size slider now scales it like any scalable face
(it used to have no effect). One authored pixel = PX_UNITS font units; the cell
is ASCENT rows above the baseline and DESCENT below, matching the old metrics.
See docs/DESIGN.md §2.1.
"""

import sys
from pathlib import Path

# --- the glyphs --------------------------------------------------------------
# key: codepoint; value: 6 rows, each 4 chars of '#'/' ' (row 0 = top).
G = {
0x20: ["...."]*6,                                  # space
0x21: [".#..",".#..",".#..",".#..","....",".#.."],  # !
0x22: [".#.#",".#.#","....","....","....","...."],  # "
0x23: [".#.#","####",".#.#","####",".#.#","...."],  # #
0x24: [".#..","####",".#.#",".#..","####",".#.."],  # $
0x25: ["#..#","..#.",".#..","#...","#..#",".#.."],  # %
0x26: [".##.","#...",".#..","#.#.","#.#.",".##."],  # &
0x27: [".#..","....","....","....","....","...."],  # '
0x28: [".#..","#...","#...","#...","#...",".#.."],  # (
0x29: [".#..","..#.","..#.","..#.","..#.",".#.."],  # )
0x2a: ["....","#.#.",".#.#","#.#.","....","...."],  # *
0x2b: ["....",".#..","####",".#..","....","...."],  # +
0x2c: ["....","....","....","....",".#..",".#.."],  # ,
0x2d: ["....","....","....","####","....","...."],  # -
0x2e: ["....","....","....","....",".#..","...."],  # .
0x2f: ["...#","..#.",".#..",".#..","#...","#..."],  # /
0x30: [".##.","#..#","#.##","##.#","#..#",".##."],  # 0 (slashed, to disambiguate from O)
0x31: [".#..","##..",".#..",".#..",".#..","###."],  # 1
0x32: [".##.","#..#","...#","..##",".#..","####"],  # 2
0x33: [".##.","...#","..#.","...#","#..#",".##."],  # 3
0x34: ["#..#","#..#","####","...#","...#","...#"],  # 4
0x35: ["####","#...","###.","...#","#..#",".##."],  # 5
0x36: [".##.","#...","###.","#..#","#..#",".##."],  # 6
0x37: ["####","...#","..#.",".#..",".#..",".#.."],  # 7
0x38: [".##.","#..#",".##.","#..#","#..#",".##."],  # 8
0x39: [".##.","#..#","#..#",".###","...#",".##."],  # 9
0x3a: ["....",".#..","....",".#..","....","...."],  # :
0x3b: ["....",".#..","....",".#..",".#..","...."],  # ;
0x3c: ["..#.",".#..","#...",".#..","..#.","...."],  # <
0x3d: ["....","####","....","####","....","...."],  # =
0x3e: [".#..","..#.","...#","..#.",".#..","...."],  # >
0x3f: [".##.","#..#","...#","..#.","....",".#.."],  # ?
0x40: [".##.","#..#","#.##","#.#.","#...",".##."],  # @
0x41: [".#..","#..#","#..#","####","#..#","#..#"],  # A
0x42: ["###.","#..#","###.","#..#","#..#","###."],  # B
0x43: [".##.","#..#","#...","#...","#..#",".##."],  # C
0x44: ["###.","#..#","#..#","#..#","#..#","###."],  # D
0x45: ["####","#...","###.","#...","#...","####"],  # E
0x46: ["####","#...","###.","#...","#...","#..."],  # F
0x47: [".##.","#..#","#...","#.##","#..#",".###"],  # G
0x48: ["#..#","#..#","####","#..#","#..#","#..#"],  # H
0x49: ["###.",".#..",".#..",".#..",".#..","###."],  # I
0x4a: ["..##","...#","...#","...#","#..#",".##."],  # J
0x4b: ["#..#","#.#.","##..","#.#.","#.#.","#..#"],  # K
0x4c: ["#...","#...","#...","#...","#...","####"],  # L
0x4d: ["#..#","####","#.##","#..#","#..#","#..#"],  # M
0x4e: ["#..#","##.#","#.##","#..#","#..#","#..#"],  # N
0x4f: [".##.","#..#","#..#","#..#","#..#",".##."],  # O
0x50: ["###.","#..#","#..#","###.","#...","#..."],  # P
0x51: [".##.","#..#","#..#","#..#","#.#.",".##."],  # Q
0x52: ["###.","#..#","#..#","###.","#.#.","#..#"],  # R
0x53: [".##.","#..#",".#..","..#.","#..#",".##."],  # S
0x54: ["####",".#..",".#..",".#..",".#..",".#.."],  # T
0x55: ["#..#","#..#","#..#","#..#","#..#",".##."],  # U
0x56: ["#..#","#..#","#..#","#..#",".#..",".#.."],  # V
0x57: ["#..#","#..#","#..#","####","####","#..#"],  # W
0x58: ["#..#","#..#",".#..",".#..","#..#","#..#"],  # X
0x59: ["#..#","#..#",".#..",".#..",".#..",".#.."],  # Y
0x5a: ["####","...#","..#.",".#..","#...","####"],  # Z
0x5b: ["###.","#...","#...","#...","#...","###."],  # [
0x5c: ["#...","#...",".#..",".#..","..#.","..#."],  # backslash
0x5d: ["###.","..#.","..#.","..#.","..#.","###."],  # ]
0x5e: [".#..","#.#.","....","....","....","...."],  # ^
0x5f: ["....","....","....","....","....","####"],  # _
0x60: [".#..","..#.","....","....","....","...."],  # `
0x61: ["....","....",".##.","#..#","#..#",".###"],  # a
0x62: ["#...","#...","###.","#..#","#..#","###."],  # b
0x63: ["....","....",".##.","#...","#...",".##."],  # c
0x64: ["...#","...#",".###","#..#","#..#",".###"],  # d
0x65: ["....","....",".##.","####","#...",".##."],  # e
0x66: ["..#.",".#..","###.",".#..",".#..",".#.."],  # f
0x67: ["....","....",".###","#..#",".###","...#"],  # g (sits at x-height, was floating a row high)
0x68: ["#...","#...","###.","#..#","#..#","#..#"],  # h
0x69: [".#..","....",".#..",".#..",".#..",".#.."],  # i
0x6a: ["..#.","....","..#.","..#.","..#.","##.."],  # j
0x6b: ["#...","#...","#.#.","##..","#.#.","#..#"],  # k
0x6c: [".#..",".#..",".#..",".#..",".#..",".##."],  # l
0x6d: ["....","....","##.#","####","#..#","#..#"],  # m
0x6e: ["....","....","###.","#..#","#..#","#..#"],  # n
0x6f: ["....","....",".##.","#..#","#..#",".##."],  # o
0x70: ["....","....","###.","#..#","#..#","###."],  # p
0x71: ["....","....",".##.","#..#","#..#",".###"],  # q (sits at x-height, was floating a row high)
0x72: ["....","....","#.#.","###.","#...","#..."],  # r
0x73: ["....","....",".##.",".#..","..#.",".##."],  # s
0x74: [".#..",".#..","###.",".#..",".#..","..#."],  # t
0x75: ["....","....","#..#","#..#","#..#",".###"],  # u
0x76: ["....","....","#..#","#..#","#..#",".#.."],  # v
0x77: ["....","....","#..#","#..#","####","#..#"],  # w
0x78: ["....","....","#..#",".#..",".#..","#..#"],  # x
0x79: ["....","....","#..#","#..#",".###","..##"],  # y
0x7a: ["....","....","####","..#.",".#..","####"],  # z
0x7b: ["..#.",".#..",".#..","#...",".#..","..#."],  # {
0x7c: [".#..",".#..",".#..",".#..",".#..",".#.."],  # |
0x7d: [".#..","..#.","..#.","...#","..#.",".#.."],  # }
0x7e: ["....","....","#..#",".#.#","..#.","...."],  # ~

# --- non-ASCII glyphs the desktop actually RENDERS in the pixel font ----------
# Built empirically (swept the panel QML, the nine apps' QML labels + Python
# user strings, and the plugin): every one below is a HARDCODED label drawn in
# this face somewhere, NOT external text (which Glyphs.px()/pylib.glyphs map to
# ASCII on the way in). Botis lacking one made its whole line fall back to
# another font and lose ~5px of ascent, clipping the row — so a missing glyph
# here is not cosmetic. Kept to what is drawn; typographic punctuation the UI
# never authors (…, em/en dash, curly quotes, • , →) is deliberately absent
# because the desktop maps it to ASCII before it ever reaches this font.
0x00b0: [".##.","#..#","#..#",".##.","....","...."],  # ° temperature unit (panel settings)
0x00b7: ["....","....",".#..","....","....","...."],  # · separator (player), star fallback
0x00d7: ["....","#..#",".##.",".##.","#..#","...."],  # × close buttons (player, viewer)
0x2016: ["#..#","#..#","#..#","#..#","#..#","...."],  # ‖ pause (viewer)
0x2039: ["..#.",".#..","#...",".#..","..#.","...."],  # ‹ previous (viewer)
0x203a: [".#..","..#.","...#","..#.",".#..","...."],  # › next (viewer)
0x2191: [".#..","###.",".#..",".#..",".#..","...."],  # ↑ sort ascending (filer)
0x2193: [".#..",".#..",".#..","###.",".#..","...."],  # ↓ sort descending (filer)
0x2212: ["....","....","####","....","....","...."],  # − zoom out (reader, viewer); bar aligns +,=
0x25a0: ["....","####","####","####","####","...."],  # ■ non-image preview placeholder (filer)
0x25b6: ["#...","###.","####","###.","#...","...."],  # ▶ play (viewer)
0x2665: ["....","#..#","####","####",".##.","...."],  # ♥ favourite (player)
0x266b: ["..##","..#.","#.#.","#.#.","###.","###."],  # ♫ now-playing marker (player)
}

# --- metrics -----------------------------------------------------------------
W, H = 4, 6          # 4 wide, 6 tall  (the authored grid; author here)
ADVANCE = 5           # 1 px right side bearing
ASCENT = 5            # rows 0..4 above/at baseline (baseline = row 4)
DESCENT = 1           # row 5 below baseline
FAMILY = "Botis 4x6"
FOUNDRY = "botis"

# Outline (scalable) metrics. One authored pixel is a PX_UNITS-square contour.
# UPM = H * PX_UNITS makes the whole 6-row cell exactly one em, so at the
# panel's 15px pixelSize one authored pixel is 15/6 = 2.5px... which is not an
# integer. To keep the old BDF's crisp 2x2-block look at 15px, the cell must be
# 12px tall at 15px pixelSize (cell/em = 12/15 = 0.8), i.e. UPM = H*PX_UNITS/0.8.
# With PX_UNITS = 100: cell = 600 units, UPM = 750, and 15px * (100/750) = 2.0px
# per authored pixel — an exact 2x2 block, pixel-identical to the old 8x12 BDF.
PX_UNITS = 100
UPM = round(H * PX_UNITS / 0.8)     # 750
ASCENT_U = ASCENT * PX_UNITS         # 500 units above the baseline
DESCENT_U = DESCENT * PX_UNITS       # 100 units below the baseline
ADVANCE_U = ADVANCE * PX_UNITS       # 500 units


def pixel_square(pen, r, c):
    """Emit one authored pixel (row r from the top, col c) as a filled square
    contour. y is baseline-relative and up-positive: the cell spans ASCENT_U
    above the baseline down to -DESCENT_U below it. Row 0 is the top row, so its
    top edge is at ASCENT_U and each row is PX_UNITS tall."""
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
    """Build the scalable outline TTF: every '#' pixel becomes a PX_UNITS square.
    Abutting squares share edges of the same winding, so the rasteriser fills the
    union — no seams — while non-adjacent ink stays separate."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    cps = sorted(G)
    glyph_order = [".notdef"] + [glyph_name(cp) for cp in cps]

    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap({cp: glyph_name(cp) for cp in cps})

    glyphs = {}
    metrics = {}
    # .notdef: empty, standard advance.
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
    fb.font["head"].lowestRecPPEM = 6
    fb.save(str(out))


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("Botis4x6.ttf")
    # sanity: all 95 printable ASCII present, all rows W wide (authored)
    ascii_cps = [cp for cp in G if 0x20 <= cp <= 0x7E]
    assert len(ascii_cps) == 95, f"expected 95 printable ASCII, got {len(ascii_cps)}"
    for cp, rows in G.items():
        assert len(rows) == H, f"U+{cp:04X}: want {H} rows"
        for r in rows:
            assert len(r) == W and set(r) <= {'.', '#'}, f"U+{cp:04X}: bad row {r!r}"
    build_ttf(out)
    print(f"wrote {out}: {len(G)} glyphs, scalable outline, UPM {UPM}, "
          f"1px={PX_UNITS}u, advance {ADVANCE_U}, ascent {ASCENT_U} descent {DESCENT_U}")


if __name__ == "__main__":
    main()
