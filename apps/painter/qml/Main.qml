import QtQuick
import QtQuick.Window

// The HYPRLAND session's window: a plain frame around `Root.qml`, which is the
// whole app. In a Plasma session this file is never loaded — main.py puts the
// same `Root.qml` inside a QMainWindow instead (`pylib/kdeshell.py`), so the
// window, its chrome and its background come from the KDE style rather than
// from here.
Window {
    id: win
    visible: true
    width: 1280
    height: 900
    minimumWidth: 720
    minimumHeight: 560
    title: "painter"
    color: Theme.bg

    Root {
        anchors.fill: parent
        // The remembered size, applied to the window rather than to itself.
        onRequestResize: (w, h) => { win.width = w; win.height = h }
    }
}
