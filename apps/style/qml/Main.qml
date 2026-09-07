import QtQuick
import QtQuick.Window

// Hyprland roof: the compositor supplies the chrome. Plasma hosts Root.qml
// directly in kdeshell's native QMainWindow so Oxygen's titlebar and window
// background are one continuous surface.
Window {
    title: "style"
    width: 980
    height: 700
    minimumWidth: 560
    minimumHeight: 420
    visible: true
    color: Theme.windowFill

    Root { anchors.fill: parent }
}
