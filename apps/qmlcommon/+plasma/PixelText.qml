import QtQuick
import QtQuick.Controls

// Forward the native font and foreground, including the parent's colour set.
Label {
    textFormat: Text.PlainText
    renderType: Text.NativeRendering
}
