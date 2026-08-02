#!/usr/bin/env python3
"""Build "Botis 4x6", a hand-authored 4-wide blocky pixel typeface, as a BDF
(and, from the derivation, a PCF). The whole of it — every pixel of every glyph
— is invented here: there is no donor face, no 4x4 pixel font exists on this
system to copy from, and the user explicitly overrode the "do not invent a
font" rule for this one face so it exists at all.

    build-4x6.py <out.bdf>

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

Hand-audited character set: all 95 printable ASCII (U+0020..U+007E).

SCALE (default 2) upscales every authored pixel to an SCALE-by-SCALE block at
BDF build time, so the emitted face is 8x12 (ascent 10, descent 2, advance 10).
The face is a pure fixed bitmap, so it is non-scalable — fontconfig pins it to
its native cell and a requested pixelSize has no effect on it. Its "default
size" therefore lives in this bitmap, not in the shared fontSize setting, and
SCALE is what sets it. 2x makes the glyph ink land tall enough to read as the
same apparent height as the desktop default (More Perfect DOS VGA at 15px,
~10px cap ink) — see docs/DESIGN.md §2.1.
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
0x2d: ["....","....","####","....","....","...."],  # -
0x2e: ["....","....","....","....",".#..","...."],  # .
0x2f: ["...#","..#.",".#..",".#..","#...","#..."],  # /
0x30: [".##.","#..#","#..#","#..#","#..#",".##."],  # 0
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
0x67: ["....",".##.","#..#","#..#",".##.","..#."],  # g
0x68: ["#...","#...","###.","#..#","#..#","#..#"],  # h
0x69: [".#..","....",".#..",".#..",".#..",".#.."],  # i
0x6a: ["..#.","....","..#.","..#.","..#.","##.."],  # j
0x6b: ["#...","#...","#.#.","##..","#.#.","#..#"],  # k
0x6c: [".#..",".#..",".#..",".#..",".#..",".##."],  # l
0x6d: ["....","....","##.#","####","#..#","#..#"],  # m
0x6e: ["....","....","###.","#..#","#..#","#..#"],  # n
0x6f: ["....","....",".##.","#..#","#..#",".##."],  # o
0x70: ["....","....","###.","#..#","#..#","###."],  # p
0x71: ["....",".###","#..#","#..#","#..#","..##"],  # q
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
}

# --- metrics -----------------------------------------------------------------
W, H = 4, 6          # 4 wide, 6 tall  (the authored grid; author here)
ADVANCE = 5           # 1 px right side bearing
ASCENT = 5            # rows 0..4 above/at baseline (baseline = row 4)
DESCENT = 1           # row 5 below baseline
SCALE = 2             # pixels per authored pixel -> emitted 8x12 face; see docstring
FAMILY = "Botis 4x6"
FOUNDRY = "botis"

# Emitted (scaled) cell — this is the face's native size and therefore its
# "default size". A fixed bitmap is non-scalable, so this is the only thing
# that sets how tall it renders.
eW, eH = W * SCALE, H * SCALE
eADVANCE = ADVANCE * SCALE
eASCENT = ASCENT * SCALE
eDESCENT = DESCENT * SCALE


def scale_glyph(rows, s):
    """Upscale a authored WxH glyph to an (W*s)x(H*s) block, crisp: each '#'
    pixel becomes an s-by-s block. This is what makes the face render taller."""
    scaled = []
    for row in rows:
        wide = "".join(ch * s for ch in row)
        for _ in range(s):
            scaled.append(wide)
    return scaled


def row_to_hex(row):
    """Pixel row -> hex string (MSB = leftmost). Width is len(row)."""
    v = 0
    n = len(row)
    for i, ch in enumerate(row):
        if ch == "#":
            v |= 1 << (n - 1 - i)
    return f"{v:0{(n + 3) // 4}X}"


def build_bdf():
    lines = []
    a = lines.append
    a("STARTFONT 2.1")
    # XLFD; spacing m (mono — every glyph advances the same eADVANCE px),
    # avgwidth in tenths of px = advance *10
    a(f"FONT -{FOUNDRY}-{FAMILY.lower().replace(' ','')}-medium-r-normal--{eH}-"
      f"{6*SCALE*10}-72-72-m-{eADVANCE*10}-iso10646-1")
    a(f"SIZE {eASCENT+eDESCENT} 72 72")
    a(f"FONTBOUNDINGBOX {eW} {eH} 0 {-eDESCENT}")
    a("STARTPROPERTIES 12")
    a(f"FONT_ASCENT {eASCENT}")
    a(f"FONT_DESCENT {eDESCENT}")
    a("DEFAULT_CHAR 32")
    a("FONT_VERSION 1.0")
    a(f"FAMILY_NAME \"{FAMILY}\"")
    a("FOUNDRY \"botis\"")
    a("WEIGHT_NAME \"Regular\"")
    a("SLANT \"R\"")
    a("SETWIDTH_NAME \"Normal\"")
    a("ADD_STYLE_NAME \"\"")
    a("CHARSET_REGISTRY \"ISO10646\"")
    a("CHARSET_ENCODING \"1\"")
    a("ENDPROPERTIES")
    a(f"CHARS {len(G)}")
    for cp in sorted(G):
        a(f"STARTCHAR U+{cp:04X}")
        a(f"ENCODING {cp}")
        a(f"SWIDTH {eADVANCE*1000} 0")
        a(f"DWIDTH {eADVANCE} 0")
        # BDF BBX yoffset is the LOWER-LEFT corner of the bitmap relative to the
        # baseline, i.e. the bottom row, not the top. The cell's bottom sits at
        # -DESCENT (descenders below the baseline); the top then lands at
        # eH-eDESCENT == eASCENT above it, as intended. The earlier value
        # (eASCENT-1) put the bottom row a whole ascent ABOVE the baseline, so
        # every glyph rendered ~11px too high and text floated to the top of any
        # box it sat in (goetia's input field, all six apps, the panel).
        a(f"BBX {eW} {eH} 0 {-eDESCENT}")
        a("BITMAP")
        for row in scale_glyph(G[cp], SCALE):
            a(row_to_hex(row))
        a("ENDCHAR")
    a("ENDFONT")
    return "\n".join(lines) + "\n"


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("Botis4x6.bdf")
    out.write_text(build_bdf())
    # sanity: every codepoint is present exactly once, all rows W wide (authored)
    assert 0x20 <= min(G) and max(G) <= 0x7E, "range"
    assert len(G) == 95, f"expected 95 printable ASCII, got {len(G)}"
    for cp, rows in G.items():
        assert len(rows) == H, f"U+{cp:04X}: want {H} rows"
        for r in rows:
            assert len(r) == W and set(r) <= {'.', '#'}, f"U+{cp:04X}: bad row {r!r}"
    print(f"wrote {out}: {len(G)} glyphs, {eW}x{eH} (authored {W}x{H}, scale {SCALE}), "
          f"advance {eADVANCE}, ascent {eASCENT} descent {eDESCENT}")


if __name__ == "__main__":
    main()
