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
    width: 1080
    height: 720
    // air's screen is a fraction of top's — let the window shrink well past
    // top's floor there (the layouts already flow; the now-playing cover has
    // its own air-side cap so it stays proportionate).
    minimumWidth: OnAir ? 320 : 480
    minimumHeight: OnAir ? 240 : 320
    title: content.windowTitle
    color: Theme.bg

    onClosing: Qt.quit()

    Root {
        id: content
        anchors.fill: parent
    }
}
