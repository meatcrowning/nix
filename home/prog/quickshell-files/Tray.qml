import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Widgets
import Quickshell.Services.SystemTray

// Vertical, interactable system tray (StatusNotifierItem).
Column {
    id: root
    spacing: Theme.gap

    // the PanelWindow that hosts this tray, needed to anchor menus
    property var hostWindow

    Repeater {
        model: SystemTray.items

        delegate: Item {
            id: entry
            required property var modelData
            readonly property var item: modelData

            width: Theme.cell
            height: Theme.cell

            // Tray icons come from the icon theme, so Theme.* colours don't
            // reach them; MultiEffect tints them to the wallpaper accent while
            // keeping the icon's own light/dark detail (colorization = 1.0).
            IconImage {
                id: trayIcon
                anchors.centerIn: parent
                implicitSize: Theme.cell - 18
                source: entry.item.icon
                visible: false
            }
            MultiEffect {
                anchors.fill: trayIcon
                source: trayIcon
                colorization: 1.0
                colorizationColor: Theme.accent
            }

            QsMenuAnchor {
                id: menu
                menu: entry.item.menu
                anchor.window: root.hostWindow
                anchor.rect.x: entry.x - 6
                anchor.rect.y: entry.y + entry.height / 2
                anchor.rect.width: 1
                anchor.rect.height: 1
                anchor.edges: Edges.Left
                anchor.gravity: Edges.Left
            }

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
                onClicked: (mouse) => {
                    if (mouse.button === Qt.LeftButton) {
                        if (entry.item.onlyMenu) menu.open();
                        else entry.item.activate();
                    } else if (mouse.button === Qt.MiddleButton) {
                        entry.item.secondaryActivate();
                    } else if (mouse.button === Qt.RightButton) {
                        menu.open();
                    }
                }
                onWheel: (wheel) =>
                    entry.item.scroll(wheel.angleDelta.y, false)
            }
        }
    }
}
