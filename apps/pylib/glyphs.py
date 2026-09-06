"""px(): make a string safe to DRAW in More Perfect DOS VGA — the apps' half.

The panel has had this for a long time (`home/prog/quickshell-files/Glyphs.qml`)
and `docs/DESIGN.md` §2.3 states the rule for the whole desktop: hardcoded UI strings
are written to suit the font, and text that arrives from OUTSIDE is mapped at
INGEST. The six apps had no mapping at all (§19.1 records that as a divergence,
and Open question 2 as the proposal); `reader` is the first app that could not
ship without one, because a markdown document is nothing BUT foreign text and
this repo's own docs are full of em dashes, curly quotes, ellipses and arrows.

WHY IT CLIPS, not just "looks wrong": a string containing a glyph the family
lacks makes Qt fall back to another font for that ONE character, the line takes
the fallback's taller ascent, and under `lineHeightMode: FixedHeight` (which
every PixelText sets, §2.2) that ascent has nowhere to go — so the whole line is
pushed down inside its row and clipped along the bottom.

``glyphmap.py`` owns the pure-Python mapping used at ingest points. This module
preserves that public API and adds only the QObject adapter needed where QML
must map at the display site. Headless parsers import ``glyphmap`` directly so
they do not pay for Qt.

**DISPLAY ONLY.** Nothing identifying goes through here — a path handed to a
process, a URL that will be opened, a search query matched against the file on
disk. Mapping those quietly opens or renames the wrong thing. Call sites that
must not map carry a comment saying so.

The table re-exported from ``glyphmap`` is a copy of the panel's, character for
character, and must stay one:
two roofs, no shared file (the panel's QML is Quickshell's, this is Python), the
same standing arrangement as `PixelText` and the `Kinetic*` types. It is a
LOOKUP TABLE, not "strip anything the font lacks" — CJK has no ASCII form, and a
title turned into question marks is worse than one drawn in the wrong font.
"""
from PySide6.QtCore import QObject, Slot
from glyphmap import (PX_MAP, UNMAPPED_BY_DESIGN, UNMAPPED_RANGES,
                      is_mappable, px)


class Glyphs(QObject):
    """`px()` for QML, as a context property — the DISPLAY-SITE half of §2.3.

    §2.3 prefers mapping at INGEST, one pass per data change, and where an app
    owns its own parse that is what it does (`reader`, `board`, `slsk`, and
    `viewer`'s `{name, path}` rows). This exists for the case §2.3 also allows —
    "map at the display site only where the model belongs to Qt or Quickshell" —
    and, more importantly, for the case ingest CANNOT serve:

    **the drawn string is also a key.** Measured across the tree 2026-08-07:
    filer's `name` is matched by `Picker.accepts()` for the file-type filter and
    is the rename dialog's prefill (written back by `mv`); player's `artist` is
    handed straight to `Library.setAlbumFilter()` when you pick "search for
    artist"; surfer's page title is Chromium's and never passes through Python
    at all. Mapping any of those at ingest would filter, rename or search for a
    string the user never typed — the exact failure §2.3 calls out.

    So the MODEL keeps the raw value and only the `text:` binding is mapped. The
    cost is a call per realised delegate rather than one per load, which is
    bounded by what is on screen; the safety is that nothing downstream of the
    model ever sees a mapped string.

        ctx.setContextProperty("Glyphs", Glyphs())     # keep a python ref
        PixelText { text: Glyphs.px(modelData.name) }
    """

    @Slot(str, result=str)
    def px(self, s):
        return px(s)
