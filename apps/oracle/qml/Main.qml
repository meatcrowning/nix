import QtQuick
import QtQuick.Window

// The HYPRLAND session's window: a plain frame around `Root.qml`, which is the
// whole of chatter. In a Plasma session this file is never loaded — main.py
// puts the same `Root.qml` inside a QMainWindow instead (`pylib/kdeshell.py`),
// so the window, its menubar, its toolbar, its status bar and its background
// come from the KDE style rather than from here.
Window {
    id: win
    width: 620
    height: 720
    visible: true
    color: Theme.bg
    title: content.windowTitle

    Root {
        id: content
        // Named so the selftest harness can reach the Root item's functions
        // from Python (a Window is not the QML root object's `Root`).
        objectName: "content"
        anchors.fill: parent
    }
}
