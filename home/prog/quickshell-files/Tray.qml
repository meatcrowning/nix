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
            // With "tint tray icons" off, show the icons in their own colours.
            IconImage {
                id: trayIcon
                anchors.centerIn: parent
                implicitSize: Theme.cell - 18
                source: entry.item.icon
                visible: !SettingsStore.d.trayTint
            }
            MultiEffect {
                anchors.fill: trayIcon
                source: trayIcon
                visible: SettingsStore.d.trayTint
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
                // The SNI Scroll() call is a discrete step to every tray app
                // that implements it (they read the delta in 120-unit wheel
                // clicks), and it is a D-Bus round trip — so notch it rather
                // than forwarding each touchpad report raw. See WheelNotch.qml.
                WheelNotch { id: notch }
                onWheel: (wheel) => {
                    const n = notch.steps(wheel);
                    if (n !== 0) entry.item.scroll(n * Kinetic.detent, false);
                }
            }
        }
    }
}
