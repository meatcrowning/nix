#!/usr/bin/env python3
"""Build the three candidate fonts the demo window compares. DEMO ONLY.

Nothing here touches the installed font, `home/pkgs/desktop/font.nix`, or
fontconfig: every output lands in ~/.cache/font-demo/ and is loaded privately by
the demo through QFontDatabase.addApplicationFont.

The three candidates (see docs/DESIGN.md S2.3 for why any of this matters):

  1. current   - the shipped More Perfect DOS VGA, byte for byte. 255 cps.
  2. merged    - the same font plus every codepoint it lacks, imported from
                 PxPlus IBM VGA 9x16 (VileR, CC BY-SA 4.0). 781 cps, U+2026
                 among them, so Qt draws a one-cell ellipsis at Text.elide.
  3. merged-noellipsis - identical to 2 with U+2026 dropped from the cmap, so
                 Qt keeps substituting three ASCII periods and existing elided
                 text is literally unchanged.

The merge is lossless: both faces are the same 8x16 VGA design on the same
em-relative grid (MPDV upm 4096 = 256 units/px, PxPlus upm 1600 = 100 units/px,
both advance 0.5625 em), so every PxPlus coordinate scales by exactly 2.56 onto
MPDV's grid with no rounding. Existing MPDV glyphs are never touched - measured
at 0 differing pixels for printable ASCII at 10/12/15/17/20/24 px.

Each output gets a DISTINCT family name, purely so the demo can address all
three at once; Qt merges same-named application fonts otherwise. The renaming is
a property of the demo build, not of any candidate.

Run:  ./build-fonts.py            (needs fontTools; font-demo.sh supplies it)
"""

import os
import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.transformPen import TransformPen
from fontTools.misc.transform import Transform

BASE = Path("/home/lam/nix/home/pkgs/desktop/font-files/MorePerfectDOSVGA.ttf")
OUT = Path(os.environ.get("FONT_DEMO_DIR", Path.home() / ".cache" / "font-demo"))

# The donor. font-demo.sh passes the nixpkgs path in; a bare run falls back to
# whatever `ultimate-oldschool-pc-font-pack` is on PATH-adjacent store paths.
DONOR = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FONT_DEMO_DONOR", "")

FAMILIES = {
    "current": "DemoCurrent MPDV",
    "merged": "DemoMerged MPDV",
    "merged-noellipsis": "DemoMergedNoEll MPDV",
}

CREDIT = (
    "More Perfect DOS VGA; extra glyphs imported from PxPlus IBM VGA 9x16 by "
    "VileR, CC BY-SA 4.0, https://int10h.org/oldschool-pc-fonts/"
)


def rename(font, family):
    """Give the face a unique family/subfamily/full/PS name."""
    for nid, value in (
        (1, family),
        (2, "Regular"),
        (3, f"{family};font-demo"),
        (4, family),
        (6, family.replace(" ", "")),
        (16, family),
        (17, "Regular"),
    ):
        for plat, enc, lang in ((3, 1, 0x409), (1, 0, 0)):
            try:
                font["name"].setName(value, nid, plat, enc, lang)
            except Exception:
                pass


def merge(donor_path):
    """Unmodified MPDV + every codepoint it lacks, scaled from the donor."""
    base = TTFont(BASE)
    donor = TTFont(donor_path)
    scale = base["head"].unitsPerEm / donor["head"].unitsPerEm
    assert scale == 2.56, f"unexpected em ratio {scale}"

    bcm, dcm = base.getBestCmap(), donor.getBestCmap()
    missing = [cp for cp in sorted(dcm) if cp not in bcm]

    dset = donor.getGlyphSet()
    glyf, hmtx = base["glyf"], base["hmtx"]
    order = list(base.getGlyphOrder())

    for cp in missing:
        name = f"uni{cp:04X}"
        if name in order:
            name += ".px"
        pen = TTGlyphPen(None)
        dset[dcm[cp]].draw(TransformPen(pen, Transform(scale, 0, 0, scale, 0, 0)))
        g = pen.glyph()
        if g.numberOfContours > 0:  # prove the grid really is exact
            coords, _, _ = g.getCoordinates(glyf)
            assert all(int(x) == x and int(y) == y for x, y in coords), cp
        glyf.glyphs[name] = g
        order.append(name)
        aw, lsb = donor["hmtx"][dcm[cp]]
        hmtx.metrics[name] = (int(round(aw * scale)), int(round(lsb * scale)))
        for t in base["cmap"].tables:
            if t.isUnicode():
                t.cmap[cp] = name

    base.setGlyphOrder(order)
    base["maxp"].numGlyphs = len(order)
    base["name"].setName(CREDIT, 13, 3, 1, 0x409)
    base["name"].setName("http://creativecommons.org/licenses/by-sa/4.0/", 14, 3, 1, 0x409)
    return base, len(missing)


def main():
    if not DONOR or not Path(DONOR).exists():
        sys.exit(
            "no donor font: set FONT_DEMO_DONOR to PxPlus_IBM_VGA_9x16.ttf "
            "(nix build nixpkgs#ultimate-oldschool-pc-font-pack), or pass it as argv[1]"
        )
    OUT.mkdir(parents=True, exist_ok=True)

    # 1 - current, untouched but renamed so it can sit beside the others
    cur = TTFont(BASE)
    rename(cur, FAMILIES["current"])
    cur.save(OUT / "current.ttf")

    # 2 - merged, with U+2026
    m, n = merge(DONOR)
    rename(m, FAMILIES["merged"])
    m.save(OUT / "merged.ttf")

    # 3 - merged, U+2026 removed from every cmap subtable (glyph left orphaned;
    #     Qt only ever reaches a glyph through the cmap)
    m2, _ = merge(DONOR)
    for t in m2["cmap"].tables:
        t.cmap.pop(0x2026, None)
    rename(m2, FAMILIES["merged-noellipsis"])
    m2.save(OUT / "merged-noellipsis.ttf")

    for f in ("current.ttf", "merged.ttf", "merged-noellipsis.ttf"):
        t = TTFont(OUT / f)
        cm = t.getBestCmap()
        print(f"{f:26} {len(cm):4} codepoints  U+2026={0x2026 in cm}  "
              f"family={t['name'].getDebugName(1)!r}")
    print(f"imported {n} codepoints from {Path(DONOR).name}")
    print(f"wrote {OUT}  (demo only - nothing installed, fontconfig untouched)")


if __name__ == "__main__":
    main()
