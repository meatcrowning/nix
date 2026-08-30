import QtQuick

// The one Text type this app uses, so every widget rasterises the pixel font
// exactly the way kitty does. Verbatim twin of the other apps' PixelText.qml
// (docs/DESIGN.md §2 — retune all copies together).
Text {
    textFormat: Text.PlainText

    font.family: Theme.font
    font.pixelSize: Theme.fontSize
    font.letterSpacing: Theme.fontLetterSpacing(Screen.devicePixelRatio)
    font.hintingPreference: Theme.fontTerminalCell ? Font.PreferVerticalHinting
                                                    : (Theme.fontSmooth ? Font.PreferNoHinting : Font.PreferFullHinting)
    renderType: Text.NativeRendering
    antialiasing: Theme.fontSmooth

    lineHeight: Theme.lineHeight
    lineHeightMode: Text.FixedHeight
}
