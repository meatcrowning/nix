import QtQuick
import QtQuick.Window
import "../qml"

// Offscreen fixture for tools/filepicker-test.py — the REAL FilePicker.qml,
// with nothing else in the window. No WebEngineView: the picker only needs
// QtWebEngine for the FileDialogRequest mode enum, and a page here would cost a
// Chromium profile for nothing.
Window {
    id: win
    width: 900
    height: 600
    visible: true

    FilePicker {
        id: picker
        objectName: "picker"
        anchors.fill: parent
    }
}
