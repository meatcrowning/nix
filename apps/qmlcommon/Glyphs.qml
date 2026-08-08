import QtQuick

// px() for QML — the DISPLAY-SITE half of docs/DESIGN.md §2.3.
//
//     import "../../qmlcommon"
//     Glyphs { id: glyphs }
//     PixelText { text: glyphs.px(modelData.name) }
//
// §2.3 prefers mapping foreign text at INGEST, one pass per data change, and
// where an app owns its own parse that is what it does (`reader`, `board`,
// `slsk`, and `viewer`'s `{name, path}` rows). This exists for the case §2.3
// also allows — "map at the display site only where the model belongs to Qt or
// Quickshell" — and for the case ingest CANNOT serve:
//
// **the drawn string is also a KEY.** Measured across the tree 2026-08-07:
// filer's `name` is what `Picker.accepts()` matches the file-type filter
// against and what the rename dialog prefills (written back by `mv`); player's
// `artist` is handed straight to `Library.setAlbumFilter()` by "search artist";
// surfer's page title is Chromium's and never passes through Python at all.
// Mapping any of those at ingest would filter, rename or search for a string
// the user never typed — the exact failure §2.3 calls out, and the reason the
// rename prefill and the drive-label editor carry "do not map" comments.
//
// So the MODEL keeps the raw value and only the `text:` binding is mapped.
//
// WHY THIS WRAPPER RATHER THAN THE CONTEXT PROPERTY DIRECTLY. `pylib/glyphs.py`
// installs a `GlyphMap` context property, and calling it bare from a binding
// means every harness and every embedding has to install it or the binding
// raises a ReferenceError. That is not hypothetical: it broke
// `player/tools/album-playnext-test.py` the moment the draw sites were mapped —
// the harness builds the real QML with its own context and had no reason to
// know about a new property, and the menu row it was clicking stopped
// triggering. The typeof guard is the same one `Motion.qml` uses on DeskStyle,
// for the same reason: an offscreen harness must get sane output, not an error.
QtObject {
    id: root

    // The mapped form of `s`, or `s` unchanged when there is no bridge — never
    // an error, and never a silently blank label.
    function px(s) {
        if (s === undefined || s === null) return "";
        if (typeof GlyphMap === "undefined" || !GlyphMap) return String(s);
        return GlyphMap.px(String(s));
    }
}
