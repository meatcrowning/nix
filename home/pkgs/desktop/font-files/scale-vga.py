#!/usr/bin/env python3
"""Emit the size-adjusted twin of the shipped More Perfect DOS VGA.

    scale-vga.py <in.ttf> <out.ttf> <factor> <family-suffix>

Run inside a derivation (home/pkgs/desktop/font.nix), never by hand — the file
that lands in ~/.local/share/fonts is this script's output. Takes the merged
face (merge-vga.py's output) and emits its " (web)" twin whose outlines,
advances and vertical metrics are all `factor` times the base face — the
font-file equivalent of a CSS `size-adjust: <factor*100>%` @font-face, with
one difference that is the whole point:

A size-adjust @font-face is the only way CSS can rescale a face, but Chromium
renders ANY @font-face-resolved face with grayscale antialiasing and ignores
the family's fontconfig `antialias=false` pin, even for a `src:local()`
source — measured offscreen 2026-08-09: the identical face via a local()
@font-face came back ~60-80% grey pixels, the plain family 0. Scaling the
FONT instead moves the size adjustment out of CSS entirely: the scaled twin
is a real installed face, matched by family name through fontconfig, so the
pins reach it and it rasterises pixel-crisp at the site's own font-sizes
(measured offscreen: the twin at a site's 16px came back 0 grey pixels,
pixel-identical to the plain face at 16 x 1.14 = 18.24px).

WHY scale metrics too, not just outlines: a site's em-based line-heights and
the face's "normal" line height come from the vertical metrics, and CSS
`size-adjust` scales those together with the glyphs (that is what kept a
site's em-based line-height intact while the ink read the size the site
assumed). Scaling outlines alone would grow the ink under an unchanged line
box — visibly tighter than the alias the factor was measured against. So
glyf outlines, hmtx advances, and the hhea/OS2 vertical metrics all get the
same factor, and the 15px em's x-height lands on the Arial/Segoe-class
baseline the same way the 114% size-adjust did (the default pick's x-height
is only ~44% of its em against the ~51% of the proportional fonts a site's
sizes were designed around — the factor is the pick's _XHEIGHT_ADJUST in
apps/surfer/main.py; a different pick has its own ratio and would need its
own measured factor before this script is pointed at it).

The factor is baked in at build time — no per-site CSS math, no @font-face —
and the twin carries the base face's full cmap (the merge's 781 codepoints).
The name table gains the suffix on the family/full/typographic-family names
(the PostScript name is sanitised — no spaces or parens); subfamily stays
Regular, and font.nix mirrors the base face's fontconfig pins for the new
family name (pattern-level weight/slant/embolden so a bold or italic REQUEST
still resolves to this Regular face, font-level antialias/hinting/rgba).

Scaling is exact on the base grid only if the factor lands scaled coordinates
on integers; 1.14 does not, so this is a *rasterisation* scale — the same
non-integer grid the size-adjust alias always rendered on, which the pixel
face survives crisply because the rasteriser grid-fits it (measured offscreen:
the plain family at 18.24px renders 0 grey pixels). The glyphs' own TrueType
instructions, if any, are left untouched: the pins drive FreeType's
autohinter, which ignores them.

The merged face is all simple glyphs (no composites); a composite glyph would
need its component transforms scaled instead of its own coordinates, so the
script refuses rather than silently mis-scales. Licence: this is Adapted
Material of the merged face (itself Adapted Material of VileR's PxPlus IBM
VGA 9x16, CC BY-SA 4.0 — the credit lives in the base face's name table and
is carried here untouched).
"""
import re
import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph


def scale_ttf(src, dst, factor, suffix):
    f = TTFont(src)
    glyf = f["glyf"]
    for name in glyf.keys():
        g = glyf[name]
        if g is None or not isinstance(g, Glyph):
            continue
        if g.isComposite():
            raise NotImplementedError(
                "composite glyph %r: scale its component transforms instead" % name)
        coords = getattr(g, "coordinates", None)
        if coords is None:
            continue  # empty glyph (.notdef, .null, the spaces) — nothing to scale
        coords.scale((factor, factor))
        coords.toInt()  # glyf stores integers; keep the grid exact

    # hmtx: advances and left bearings scale with the outlines.
    hmtx = f["hmtx"]
    for name in list(hmtx.metrics.keys()):
        adv, lsb = hmtx.metrics[name]
        hmtx.metrics[name] = (round(adv * factor), round(lsb * factor))

    # Vertical metrics: hhea + OS/2, so em-based line heights scale with the
    # ink exactly as size-adjust did.
    hhea = f["hhea"]
    for attr in ("ascent", "descent", "lineGap", "advanceWidthMax",
                 "minLeftSideBearing", "minRightSideBearing", "xMaxExtent"):
        setattr(hhea, attr, round(getattr(hhea, attr) * factor))
    os2 = f["OS/2"]
    for attr in ("sTypoAscender", "sTypoDescender", "sTypoLineGap",
                 "usWinAscent", "usWinDescent", "sxHeight", "sCapHeight"):
        setattr(os2, attr, round(getattr(os2, attr) * factor))

    # head bbox: uniform scale with no translation, so the bounding box is the
    # base bbox times the factor exactly (rounded to the integer grid).
    head = f["head"]
    for attr in ("xMin", "yMin", "xMax", "yMax"):
        setattr(head, attr, round(getattr(head, attr) * factor))

    # The face's own name gains the suffix; subfamily stays Regular. The
    # PostScript name (ID 6) is sanitised — PS names allow only alnum + '-'.
    name = f["name"]
    fam = [n.toUnicode() for n in name.names if n.nameID == 1][0]
    ps_suffix = re.sub(r"[^A-Za-z0-9-]", "-", suffix).strip("-")
    for nid in (1, 4, 16):
        for rec in name.names:
            if rec.nameID == nid:
                rec.string = rec.toUnicode() + suffix
    for rec in name.names:
        if rec.nameID == 6:
            rec.string = rec.toUnicode() + ps_suffix

    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    f.save(dst)
    print(
        f"{Path(src).name} -> {Path(dst).name}: family '{fam}{suffix}' "
        f"({len(glyf.glyphs)} glyphs, factor {factor:g})"
    )


def main():
    src, dst, factor, suffix = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
    assert factor > 1, "a scale-down twin is not what any consumer asks for"
    scale_ttf(src, dst, factor, suffix)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(2)
    main()
