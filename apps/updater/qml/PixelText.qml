import QtQuick

// The one Text type this app uses, so every widget rasterises the pixel font
// exactly the way kitty does. Verbatim twin of the other apps' PixelText.qml
// (docs/DESIGN.md §2 — retune all copies together).
Text {
    textFormat: Text.PlainText

    font: (typeof DeskStyle !== "undefined" && DeskStyle
           && typeof DeskStyle.labelFontForScale === "function")
          ? DeskStyle.labelFontForScale(Screen.devicePixelRatio)
          : Qt.font({ family: Theme.font, pixelSize: Theme.fontSize,
                      hintingPreference: Theme.fontTerminalCell
                                         ? Font.PreferVerticalHinting
                                         : (Theme.fontSmooth ? Font.PreferNoHinting
                                                             : Font.PreferFullHinting) })
    renderType: Text.NativeRendering
    antialiasing: Theme.fontSmooth
    readonly property bool oxygenExternal: (typeof DeskStyle !== "undefined" && DeskStyle && DeskStyle.topFontTreatment) && Theme.font === "Oxygen Mono"
                                        && Screen.devicePixelRatio <= 1.01
    style: oxygenExternal ? Text.Outline : Text.Normal
    styleColor: oxygenExternal ? Qt.rgba(color.r, color.g, color.b, 0.12) : color

    lineHeight: Theme.lineHeight
    lineHeightMode: Text.FixedHeight
}
