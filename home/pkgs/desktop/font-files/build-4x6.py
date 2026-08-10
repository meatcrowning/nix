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

OUTPUT IS A SCALABLE OUTLINE TTF, not a bitmap. Each glyph is the MERGED union
outline of its authored pixel squares (see merged_contours), so the face is a
normal scalable font that any renderer can rasterise. This is deliberate and load-bearing: as a non-scalable BDF the
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
# key: codepoint; value: 6 rows, each 4 chars of '#'/'.' (row 0 = top).
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
# here is not cosmetic.
#
# Most typographic punctuation the UI never authors (…, •, →) stays absent on
# purpose: the desktop maps it to ASCII at ingest (Glyphs.px()/pylib.glyphs)
# before it reaches this font. But that ingest mapping is only wired into the
# panel and reader — the six other apps parse foreign metadata (an ID3 title
# like "Don't Stop") and draw it raw, so a curly apostrophe/quote or an en/em
# dash from a real tag DOES reach this face and clipped the player's rows. Those
# few characters are therefore carried here (mapped to their ASCII twins' shapes,
# which is what px() would have produced anyway) so any app is safe without its
# own ingest pass. More Perfect DOS VGA already covers them; this is parity.
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
0x2588: ["####","####","####","####","####","####"],  # █ full block — progress-bar fill (surfer, filer video convert)
0x2591: ["#...","..#.","#...","..#.","#...","..#."],  # ░ light shade — progress-bar empty track (dithered)
0x25b6: ["#...","###.","####","###.","#...","...."],  # ▶ play (viewer)
0x2665: ["....","#..#","####","####",".##.","...."],  # ♥ favourite (player)
0x266b: ["..##","..#.","#.#.","#.#.","###.","###."],  # ♫ now-playing marker (player)

# Typographic punctuation that arrives in FOREIGN text (ID3 tags, filenames)
# and reaches this face because the six non-panel/reader apps do not px()-map at
# ingest. Each reuses its ASCII twin's shape — px() would map it to that ASCII
# char anyway — so a curly apostrophe no longer forces a taller fallback and
# clips the row. Parity with More Perfect DOS VGA, which already carries these.
0x2018: [".#..","....","....","....","....","...."],  # ' left single quote  (= ')
0x2019: [".#..","....","....","....","....","...."],  # ' right single quote / apostrophe (= ')
0x201c: [".#.#",".#.#","....","....","....","...."],  # " left double quote  (= ")
0x201d: [".#.#",".#.#","....","....","....","...."],  # " right double quote (= ")
0x2013: ["....","....","....","####","....","...."],  # – en dash  (= -)
0x2014: ["....","....","....","####","....","...."],  # — em dash  (= -)
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
ASCENT_U = ASCENT * PX_UNITS         # 500 units above the baseline (GLYPH geometry)
DESCENT_U = DESCENT * PX_UNITS       # 100 units below the baseline (GLYPH geometry)
ADVANCE_U = ADVANCE * PX_UNITS       # 500 units

# LINE-BOX metrics carry the leading the glyph cell does not. ASCENT_U/DESCENT_U
# above are the GLYPH outline extents — the authored 6-row cell is 600u, ink
# flush to both edges. Handing that same 600u to the hhea/OS2 line box packs
# rows with ZERO gap: a descender (row 5) touches the next line's cap (row 0),
# which reads as cramped/compressed line spacing EVERYWHERE the face is used
# (measured: QFontMetrics.height() = 12px at 15px, against the DOS faces' 15px —
# that 3px is real leading, not "dead" leading to remove). So the line box is a
# full em (UPM), the same line height More Perfect DOS VGA carries (ascent 11 /
# descent 4 at 15px), distributed to match it: 1px of air above the caps and 2px
# below the descenders. Glyph OUTLINES are untouched — this only sizes the line
# box, so a row measures 15px at 15px like every other face and rows breathe the
# same. deskstyle.py's lineHeight table and DESIGN.md §2.1 track these numbers.
FACE_ASCENT_U = 550                  # 500u glyph + 50u (1px) air above caps
FACE_DESCENT_U = UPM - FACE_ASCENT_U # 200u: 100u glyph + 100u (2px) below descenders


def merged_contours(rows):
    """Trace a glyph's ink as MERGED rectilinear contours — the union outline,
    not one square per pixel. Coordinates are font units, y up, baseline 0:
    row 0's top edge is at ASCENT_U and each row is PX_UNITS tall.

    Why merged (2026-08-08): as per-pixel squares, every seam between two
    vertically adjacent ink pixels was a pair of coincident edges, and any
    grid-fitting rasteriser that snaps those edges independently pulls them
    apart — Chromium (surfer) FORCE-enables the FreeType autohinter whenever a
    face is fontconfig-pinned antialias=off, no matter what the hinting pin
    says (measured: hintnone honoured with AA on, forced autohint with AA
    off), and at any size off the exact 15px grid every glyph was sliced by
    blank horizontal stripes. A union outline has no interior edges, so there
    is nothing to pull apart; More Perfect survives the same autohint because
    its outlines are merged, and now Botis matches.

    Boundary edges are emitted ink-on-left, so outer contours come out CCW —
    the same winding the old squares had — and holes CW, both filled by
    nonzero winding. At a checkerboard corner (two ink pixels touching
    diagonally) four edges meet at one vertex; taking the leftmost turn keeps
    the two squares as separate loops touching at a point instead of a
    self-crossing bowtie."""
    ink = set()
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch == "#":
                ink.add((r, c))

    def corners(r, c):
        x0 = c * PX_UNITS
        y1 = ASCENT_U - r * PX_UNITS     # top edge of this row
        return x0, x0 + PX_UNITS, y1 - PX_UNITS, y1   # x0 x1 y0 y1

    edges = set()                        # directed (start, end), ink on the left
    for (r, c) in ink:
        x0, x1, y0, y1 = corners(r, c)
        if (r + 1, c) not in ink:        # bottom edge, ink above -> +x
            edges.add(((x0, y0), (x1, y0)))
        if (r - 1, c) not in ink:        # top edge, ink below -> -x
            edges.add(((x1, y1), (x0, y1)))
        if (r, c - 1) not in ink:        # left edge, ink right -> -y
            edges.add(((x0, y1), (x0, y0)))
        if (r, c + 1) not in ink:        # right edge, ink left -> +y
            edges.add(((x1, y0), (x1, y1)))

    out = {}
    for s, e in edges:
        out.setdefault(s, []).append(e)

    def direction(a, b):
        return (b[0] - a[0]) // PX_UNITS or 0, (b[1] - a[1]) // PX_UNITS or 0

    contours = []
    unused = set(edges)
    while unused:
        start, nxt = min(unused)         # deterministic output
        unused.discard((start, nxt))
        pts = [start]
        cur = nxt
        d = direction(start, nxt)
        while cur != start:
            pts.append(cur)
            outs = [e for e in out[cur] if (cur, e) in unused]
            # leftmost turn first: max cross(d, candidate direction)
            nxt_pt = max(outs, key=lambda e: d[0] * direction(cur, e)[1]
                         - d[1] * direction(cur, e)[0])
            unused.discard((cur, nxt_pt))
            d = direction(cur, nxt_pt)
            cur = nxt_pt
        # drop collinear midpoints (runs of unit edges in one direction)
        slim = []
        n = len(pts)
        for i, p in enumerate(pts):
            a, b = pts[i - 1], pts[(i + 1) % n]
            if direction(a, p) != direction(p, b):
                slim.append(p)
        contours.append(slim)
    return contours


def glyph_name(cp):
    return "space" if cp == 0x20 else f"uni{cp:04X}"


def build_ttf(out):
    """Build the scalable outline TTF: each glyph is the merged union outline
    of its PX_UNITS ink squares (see merged_contours for why per-pixel square
    contours were replaced)."""
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
        for contour in merged_contours(G[cp]):
            pen.moveTo(contour[0])
            for p in contour[1:]:
                pen.lineTo(p)
            pen.closePath()
        glyphs[glyph_name(cp)] = pen.glyph()
        # Mono: every glyph advances ADVANCE_U; LSB left at 0 (the grid origin).
        metrics[glyph_name(cp)] = (ADVANCE_U, 0)

    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=FACE_ASCENT_U, descent=-FACE_DESCENT_U)
    fb.setupNameTable({
        "familyName": FAMILY,
        "styleName": "Regular",
        "fullName": FAMILY,
        "psName": FAMILY.replace(" ", "") + "-Regular",
        "version": "1.0",
        "uniqueFontIdentifier": f"{FOUNDRY};{FAMILY};1.0",
    })
    fb.setupOS2(
        sTypoAscender=FACE_ASCENT_U, sTypoDescender=-FACE_DESCENT_U, sTypoLineGap=0,
        usWinAscent=FACE_ASCENT_U, usWinDescent=FACE_DESCENT_U,
    )
    # USE_TYPO_METRICS (fsSelection bit 7) makes the padded typo line box above
    # AUTHORITATIVE. Without it Qt/FreeType (and so every consumer: the apps, the
    # Quickshell panel, the Pango titlebar) size a text row from the GLYPH
    # BOUNDING BOX — 600u / 12px at 15px, ink flush to both edges — and the
    # leading is discarded, which is exactly the cramped spacing this fixes
    # (measured: bit clear -> QFontMetrics.height 12px, bit set -> 15px, matching
    # More Perfect DOS VGA). Bit 6 marks the face Regular.
    fb.font["OS/2"].fsSelection = (1 << 6) | (1 << 7)
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
