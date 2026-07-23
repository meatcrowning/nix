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
}
