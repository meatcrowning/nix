import QtQuick
import QtQuick.Window

// The HYPRLAND session's window: a plain frame around Root.qml. Under Plasma
// this file is never loaded; main.py hosts Root.qml in a kdeshell window.
Window {
    id: win
    width: 1280
    height: 860
    minimumWidth: 560
    minimumHeight: 420
    visible: true
    color: Theme.bg
    title: content.windowTitle

    // Basic controls take the wallpaper palette here; the native style owns
    // them under Plasma.
    palette.window: Theme.bg
    palette.windowText: Theme.text
    palette.base: Theme.bgAlt
    palette.alternateBase: Theme.bgAlt
    palette.text: Theme.text
    palette.button: Theme.bgAlt
    palette.buttonText: Theme.text
    palette.highlight: Theme.highlight
    palette.highlightedText: Theme.accent
    palette.placeholderText: Theme.textDim
    palette.mid: Theme.border
    palette.dark: Theme.border

    Root {
        id: content
        objectName: "content"
        anchors.fill: parent
    }
}
