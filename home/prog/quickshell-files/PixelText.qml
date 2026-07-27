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
// Sizes are pixels (Theme.fontSize), not points: point sizes get scaled by DPI
// to a fractional pixel height that lands between the font's design grid and
// reintroduces blur. Integer pixel sizes on the 16px grid stay sharp.
Text {
    font.family: Theme.font
    font.pixelSize: Theme.fontSize
    font.hintingPreference: Font.PreferFullHinting
    renderType: Text.NativeRendering
    antialiasing: false

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
    // line), so multi-line/wrapped text leads ~1px wider than kitty's 15px cell
    // and it compounds down a paragraph. Pin the per-line height to the pixel
    // size (== kitty's cell) so every line sits flush like a terminal row.
    lineHeight: Theme.fontSize
    lineHeightMode: Text.FixedHeight
}
