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
    // PLAIN TEXT, ALWAYS. This dialog renders two caller-supplied strings
    // (sudo's argv[1] prompt and $SUDO_ASKPASS_REASON). QML's Text defaults to
    // AutoText, which sniffs for HTML and INTERPRETS it — that would let any
    // caller style a password prompt, forge its chrome, or hide text. main.py's
    // sanitize() strips control characters and clamps length; this line is the
    // other half, and it must stay on every label in this app.
    textFormat: Text.PlainText

    font: (typeof DeskStyle !== "undefined" && DeskStyle
           && typeof DeskStyle.labelFontForScale === "function")
          ? DeskStyle.labelFontForScale(Screen.devicePixelRatio)
          : Qt.font({ family: Theme.font, pixelSize: Theme.fontSize,
                      hintingPreference: Theme.fontTerminalCell
                                         ? Font.PreferVerticalHinting
                                         : (Theme.fontSmooth ? Font.PreferNoHinting
                                                             : Font.PreferFullHinting) })
    // PIXEL-FACE settings — except when the live face is a smooth outline
    // (Theme.fontSmooth <- DeskStyle.smooth: Phenex, the cursive). Then the
    // crisp pipeline is exactly wrong (staircased curves, kinked joins):
    // keep NativeRendering but antialias and drop hinting, matching the
    // face's fontconfig rule and docs/DESIGN.md 2.2.
    renderType: Text.NativeRendering
    antialiasing: Theme.fontSmooth
    readonly property bool oxygenExternal: (typeof DeskStyle !== "undefined" && DeskStyle && (DeskStyle.topFontTreatment || DeskStyle.airFontTreatment)) && Theme.font === "Oxygen Mono" && Screen.devicePixelRatio <= 1.01
    style: oxygenExternal ? Text.Outline : Text.Normal
    styleColor: oxygenExternal ? Qt.rgba(color.r, color.g, color.b, (typeof DeskStyle !== "undefined" && DeskStyle && DeskStyle.airFontTreatment) ? 0.22 : 0.12) : color

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
