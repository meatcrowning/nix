pragma Singleton
import QtQuick
import Quickshell

// px(): make a string safe to draw in the panel's pixel font.
//
// Hardcoded UI strings can be written to suit More Perfect DOS VGA, and the
// rule in AGENTS.md says they must be. Text that arrives from OUTSIDE cannot:
// track tags, window titles, filenames, notification bodies and process names
// are whatever the world hands us. This is where that text is mapped onto the
// font on the way in.
//
// Neutral on purpose. It started life inside the Media singleton, for the play
// queue, but the same clipping hits every widget that draws text it did not
// author, so it does not belong to any one of them.
Singleton {
    id: root

    // Every label on this panel is a PixelText in More Perfect DOS VGA, and that
    // font's cmap stops at Latin-1 plus a handful of box/dot glyphs. A string
    // containing a glyph it does not have makes Qt fall back to Noto Sans for
    // that ONE character — and the line's ascent becomes the fallback's, which
    // is taller. With `lineHeightMode: FixedHeight` pinning the line box to
    // Theme.fontSize the extra ascent has nowhere to go, so the whole line is
    // pushed down inside its row and clipped along the bottom. That is the
    // "one apostrophe ruins the row" report: the title sits several pixels
    // lower than the number, artist and duration beside it, which are ASCII.
    //
    // Music metadata is full of typographic punctuation — 427 of the 11k tracks
    // in the library have U+2019 in the title or artist, 140 have U+2010 — so
    // this is not an edge case. Each of these has an exact ASCII equivalent
    // that reads the same at 16px, and the substitution is DISPLAY ONLY: the
    // tags on disk are untouched, and nothing that identifies a track (the
    // MPRIS id, the queue index sent back over the socket) goes through here.
    //
    // Deliberately NOT a general "strip anything the font lacks": ~830 tracks
    // are vaporwave with CJK or fullwidth titles, which have no ASCII form at
    // all. Those still fall back — and still sit low — but a title replaced by
    // question marks would be worse than one drawn in the wrong font. Fixing
    // them needs a pixel font with CJK coverage, not a lookup table.
    //
    // Written with \u escapes for the keys that are invisible or
    // confusable; the visible ones stay literal so the table reads.
    readonly property var _pxMap: ({
        "\u2018": "'",  "\u2019": "'",  "\u201a": "'",  "\u201b": "'",
        "\u02bc": "'",  "\u00b4": "'",  "\u2032": "'",
        "\u201c": "\"", "\u201d": "\"", "\u201e": "\"", "\u201f": "\"",
        "\u2033": "\"",
        "\u2010": "-",  "\u2011": "-",  "\u2012": "-",  "\u2013": "-",
        "\u2014": "-",  "\u2015": "-",  "\u2212": "-",
        "\u2026": "...", "\u2022": "*",  "\u2044": "/",
        "\ufb01": "fi", "\ufb02": "fl",
        "\u2007": " ",  "\u202f": " ",  "\u200b": "",
        "\u2190": "<-", "\u2192": "->", "\u2191": "^",  "\u2193": "v",
        "\u2039": "<",  "\u203a": ">",  "\u2043": "-",  "\u2023": "-",
        "\u2122": "(tm)", "\u00a9": "(c)", "\u00ae": "(r)", "\u2117": "(p)",
        "\u00d7": "x",  "\u00be": "3/4", "\u00f8": "o"
    })
    readonly property string _pxClass:
        "[\\u2010-\\u2015\\u2018-\\u201f\\u2022\\u2023\\u2026\\u2032"
        + "\\u2033\\u2039\\u203a\\u2043\\u2044\\u2007\\u200b\\u202f"
        + "\\u2117\\u2122\\u2190\\u2191\\u2192\\u2193\\u2212\\u02bc"
        + "\\u00a9\\u00ae\\u00b4\\u00be\\u00d7\\u00f8\\ufb01\\ufb02]"
    readonly property var _pxRe: new RegExp(_pxClass)
    readonly property var _pxReG: new RegExp(_pxClass, "g")
    function px(s) {
        if (!s || !_pxRe.test(s)) return s || "";
        return s.replace(_pxReG, c => root._pxMap[c]);
    }
}
