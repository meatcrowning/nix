import QtQuick

// A paragraph of the board's own prose, wrapped.
//
// board draws whole paragraphs rather than reader's per-word runs, and that is
// the right trade HERE: this file is a few dozen short blocks, not a
// 2300-line document being scrolled, so the per-delegate cost reader had to
// engineer away never arises — while `PixelText`'s FixedHeight packing gives
// the same kitty-exact leading either way (docs/DESIGN.md §2.1).
//
// Every string reaching this item has already been glyph-mapped at INGEST, in
// `boardparse.text()` (§2.3). Nothing here maps at the draw site.
PixelText {
    wrapMode: Text.WordWrap
    // Height follows the wrap. A paragraph in a Column must report the height
    // it actually took, or the rows below it draw on top of it.
    height: implicitHeight
}
