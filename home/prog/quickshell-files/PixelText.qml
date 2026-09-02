import QtQuick

// The one Text type the whole panel uses, so every widget rasterises the pixel
// font exactly the way kitty does.
//
// QML's default Text uses renderType Text.QtRendering — a distance-field glyph
// renderer meant for smooth scalable fonts; it antialiases the edges and turns a
// bitmap/pixel font ("More Perfect DOS VGA") into a blurry mush that looks
// nothing like the terminal. Text.NativeRendering rasterises through FreeType at
// device pixels, honouring hinting and the font's native strikes, giving the
// same crisp, hard-edged pixels kitty draws.
//
// Pixel faces use the desktop's integer pixel size.  Terminal-cell faces use
// Kitty's generated point size instead, because that is the glyph raster the
// terminal actually draws; Theme then measures and snaps the resulting cell.
//
// ALL OF THAT IS FOR PIXEL FACES. When the live face is a smooth outline
// (Theme.fontSmooth — Phenex, the cursive), the same settings are exactly
// wrong: NativeRendering + no AA + full hinting turns its curves into a
// jagged staircase and kinks the connected joins. A smooth face keeps
// NativeRendering (FreeType honours the face's fontconfig rule: grayscale AA,
// no hinting — the same rasterisation kitty and the titlebar give it) but
// with antialiasing on and hinting off.
Text {
    // A complete value avoids QML retaining the preceding pixel size when the
    // terminal-cell branch supplies Kitty's point size.
    font: Theme.fontForScale(Screen.devicePixelRatio)
    renderType: Text.NativeRendering
    antialiasing: Theme.fontSmooth
    // Oxygen Mono has no real bold face. Qt silently resolves every requested
    // weight to Regular, whereas Kitty's glyph shader carries a visibly fuller
    // edge. Its same-colour outline supplies that missing edge without changing
    // the family or touching the other selectable faces.
    readonly property bool oxygenExternal: (Theme.topFontTreatment || Theme.airFontTreatment) && Theme.font === "Oxygen Mono"
                                        && Screen.devicePixelRatio <= 1.01
    style: oxygenExternal ? Text.Outline : Text.Normal
    styleColor: oxygenExternal ? Qt.rgba(color.r, color.g, color.b,
                                         Theme.airFontTreatment ? 0.22 : 0.12) : color

    // Text defaults to AutoText, which SNIFFS for HTML and renders it as rich
    // text. Nearly everything the panel draws is a string from somewhere else —
    // window titles, process names, filenames, notification bodies — so that
    // default hands any app on the notification bus a markup renderer: an
    // <img src="http://…"> in a notification body becomes a real fetch, i.e. a
    // read beacon. Notifications.plain() strips tags but then UNESCAPES
    // entities, so &lt;img&gt; survives the strip and is reborn as markup here.
    // Pin plain text at the one type every widget uses; individual PlainText
    // pins in Tooltip.qml and TaskMenu.qml predate this and are now redundant.
    textFormat: Text.PlainText

    // Match kitty's line packing. The font's line box is exactly 1 em, but Qt
    // rounds ascent/descent UP separately (at 15px: 11.25→12 + 3.75→4 = 16px per
    // line), so multi-line/wrapped text leads ~1px wider than the face's own
    // cell and it compounds down a paragraph. Pin the per-line height to that
    // cell so every line sits flush like a terminal row.
    //
    // The cell is Theme.lineHeight, MEASURED off the live face — not
    // Theme.fontSize. For the DOS faces the two are the same 15px; for Botis
    // 4x6 the cell is 12px at that size, and pinning 15 here padded every line
    // in the panel with 3px of leading it did not ask for.
    lineHeight: Theme.lineHeight
    lineHeightMode: Text.FixedHeight
}
