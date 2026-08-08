#!/usr/bin/env python3
"""Build the shipped More Perfect DOS VGA: the original, plus the codepoints it
lacks, imported from PxPlus IBM VGA 9x16.

    merge-vga.py <base.ttf> <donor.ttf> <out.ttf> [label]

Run inside a derivation (home/pkgs/desktop/font.nix), never by hand — the file
that lands in ~/.local/share/fonts is this script's output, so editing the
script is how the desktop's font changes. label (optional, defaults to the
source file's stem) names the base face in the PxPlus attribution.

It builds the More Perfect DOS VGA default (font.nix calls it once per face it
merges; the Perfect DOS VGA 437 alternative it also built was dropped
2026-08-08 on his call, but the script stays face-agnostic).

WHY, and what is guaranteed
---------------------------
More Perfect DOS VGA covers 255 codepoints. docs/DESIGN.md S2.3 is one long
account of what that costs: a string carrying a character the family lacks takes
another font's taller ascent for that one glyph, and under `FixedHeight` the
whole line is pushed down inside its row and clipped. It has been fixed at least
seven times, and 43 ordinary Latin-1 letters (`A` with every accent, `O/`, `TH`,
...) still clip in European filenames, which no glyph table can rewrite away.

Replacing the font outright is not an option — PxPlus alone is metrically
identical but redraws 9 ASCII glyphs, and at the sizes actually used 70 of 95
printable ASCII characters come out different. So: keep every existing glyph
byte for byte, and import ONLY what is missing. 255 -> 781 codepoints.

The import is exact, not approximate. Both faces are the same 8x16 VGA design on
the same em-relative grid: MPDV is 4096 upm (256 units/px), PxPlus is 1600 upm
(100 units/px), and both advance 0.5625 em. So every donor coordinate scales by
exactly 2.56 onto MPDV's grid and lands on an integer — asserted below on every
imported point, so a future nixpkgs bump of the donor cannot silently start
rounding. Of the 149 codepoints the two share, none is touched: the base font's
`glyf`, `cmap` and `hmtx` entries are only ever appended to.

U+2026 comes with it — HIS call, 2026-07-28, on the demo in tools/font-demo
("Merge, and take the real ellipsis"). It is the one place ordinary text visibly
changes: Qt substitutes three ASCII periods for an elided string only while the
family has no ellipsis glyph, so ~45 `Text.elide` call sites across the panel and
the apps switch to a real one-cell ellipsis. That does not clip (the glyph is now
in the family, so no fallback) and it buys back two cells of text. DESIGN.md
S2.2 records the change; do not hand-roll an ASCII elide to undo it.

Licence: the imported outlines are PxPlus IBM VGA 9x16 by VileR, CC BY-SA 4.0.
The output is Adapted Material and carries the credit in its `name` table
(IDs 13/14), which is why this repo commits a script and not a .ttf.
"""

import sys
from pathlib import Path

from fontTools.misc.transform import Transform
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

LICENSE_URL = "http://creativecommons.org/licenses/by-sa/4.0/"

# % (label) is the base font's family, so each face carries its own attribution.
CREDIT = (
    "%s; glyphs it lacked imported from PxPlus IBM VGA 9x16 "
    "by VileR, CC BY-SA 4.0, https://int10h.org/oldschool-pc-fonts/"
)


def merge(base_path, donor_path, label):
    base = TTFont(base_path)
    donor = TTFont(donor_path)

    scale = base["head"].unitsPerEm / donor["head"].unitsPerEm
    assert scale == 2.56, f"unexpected em ratio {scale}: the grids no longer line up"

    # A snapshot, not a reference: getBestCmap() hands back the live subtable,
    # which the loop below mutates — so the "nothing moved" check in main() only
    # means anything against a copy taken first.
    bcm, dcm = dict(base.getBestCmap()), donor.getBestCmap()
    missing = [cp for cp in sorted(dcm) if cp not in bcm]

    dset = donor.getGlyphSet()
    glyf, hmtx = base["glyf"], base["hmtx"]
    order = list(base.getGlyphOrder())

    for cp in missing:
        name = f"uni{cp:04X}"
        if name in order:  # the base font already uses that name for something else
            name += ".px"
        pen = TTGlyphPen(None)
        dset[dcm[cp]].draw(TransformPen(pen, Transform(scale, 0, 0, scale, 0, 0)))
        g = pen.glyph()
        if g.numberOfContours > 0:  # prove the grid really is exact
            coords, _, _ = g.getCoordinates(glyf)
            assert all(int(x) == x and int(y) == y for x, y in coords), (
                f"U+{cp:04X} did not land on the grid"
            )
        glyf.glyphs[name] = g
        order.append(name)
        aw, lsb = donor["hmtx"][dcm[cp]]
        hmtx.metrics[name] = (int(round(aw * scale)), int(round(lsb * scale)))
        for t in base["cmap"].tables:
            if t.isUnicode():
                t.cmap[cp] = name

    base.setGlyphOrder(order)
    base["maxp"].numGlyphs = len(order)

    # Attribution rides in the file, per CC BY-SA 4.0. The family name is NOT
    # touched: fontconfig's regular-only rule, Theme.qml, kitty.conf and eight
    # apps all address this face as "More Perfect DOS VGA".
    base["name"].setName(CREDIT % label, 13, 3, 1, 0x409)
    base["name"].setName(LICENSE_URL, 14, 3, 1, 0x409)
    return base, bcm, missing


def main():
    base_path, donor_path, out_path, *rest = sys.argv[1:5]
    label = rest[0] if rest else Path(base_path).stem
    merged, before, imported = merge(base_path, donor_path, label)

    after = merged.getBestCmap()
    for cp, name in before.items():  # nothing that existed may have moved
        assert after[cp] == name, f"U+{cp:04X} was remapped"
    assert 0x2026 in after, "the ellipsis did not make it in"

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    merged.save(out_path)
    print(
        f"{len(before)} -> {len(after)} codepoints "
        f"({len(imported)} imported from {Path(donor_path).name}, "
        f"0 of the original {len(before)} altered)"
    )


if __name__ == "__main__":
    main()
