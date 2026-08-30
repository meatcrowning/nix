import QtQuick

// qmlcommon's copy of the apps' PixelText — byte-identical to the one eight of
// them carry in their own `qml/` (docs/DESIGN.md §2.2). It exists because a
// component in THIS directory cannot reach an app's copy: file components
// resolve per-directory, which is exactly why §7.2 records `SelectButton.qml`
// as "a verbatim copy in player and filer ... it needs PixelText, which a
// qmlcommon component cannot reach". `DeskMenuBar.qml` needed the same type and
// one shared copy here is cheaper than a tenth per-app one. Retune all of them
// together.
//
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
    // PLAIN TEXT, ALWAYS. QML's Text defaults to AutoText, which sniffs for
    // HTML and INTERPRETS it — so any string this app did not write itself (a
    // filename, an ID3 tag, a web page title, a JS alert() body, a portal
    // caller's dialog title) could style the chrome, hide text, or pull a
    // remote <img>. Every label in every one of these apps goes through this
    // type, so pinning it here is the whole defence. Nothing in this tree
    // relies on markup being rendered: the one ingest point that receives it
    // (the panel's Notifications.plain()) strips tags instead.
    textFormat: Text.PlainText

    font.family: Theme.font
    font.pixelSize: Theme.fontSize
    // PIXEL-FACE settings — except when the live face is a smooth outline
    // (Theme.fontSmooth <- DeskStyle.smooth: Phenex, the cursive). Then the
    // crisp pipeline is exactly wrong (staircased curves, kinked joins):
    // keep NativeRendering but antialias and drop hinting, matching the
    // face's fontconfig rule and docs/DESIGN.md 2.2.
    font.hintingPreference: Theme.fontNativeHinting ? Font.PreferDefaultHinting
                                                  : (Theme.fontSmooth ? Font.PreferNoHinting : Font.PreferFullHinting)
    renderType: Text.NativeRendering
    antialiasing: Theme.fontSmooth

    // Match kitty's line packing. The font's line box is exactly 1 em, but Qt
    // rounds ascent/descent UP separately (at 15px: 11.25→12 + 3.75→4 = 16px per
    // line), so multi-line/wrapped text leads ~1px wider than the face's own
    // cell and it compounds down a paragraph. Pin the per-line height to that
    // cell so every line sits flush like a terminal row.
    //
    // The cell is Theme.lineHeight, MEASURED off the live face — not
    // Theme.fontSize. For the DOS faces the two are the same 15px at the default;
    // for Botis 4x6 the cell is 12px at that size, and pinning the em size here
    // padded every label in every app with leading it did not ask for. The panel's
    // copy of this file was fixed when Theme.lineHeight was added there; the apps
    // had no such property until 2026-08-07, which is why they kept the old pin.
    lineHeight: Theme.lineHeight
    lineHeightMode: Text.FixedHeight
}
