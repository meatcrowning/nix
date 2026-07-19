import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets

// Vertical list of RUNNING PROGRAMS (this desktop is locked to a single
// workspace — these replaced the old workspace squares). One cell per
// toplevel, real app icon, focused window gets the accent treatment the
// active workspace cell used to have; everything else the dim outline.
//
// Clicking a cell activates its window. That's also how minimized windows
// come back: the hyprvtb titlebar plugin slides a minimized window off the
// right screen edge and slides it back in when the window is focused again
// — which is exactly what activate() causes.
//
// Uses the Wayland foreign-toplevel list (works standalone on this build;
// it's only the Hyprland IPC *mapping* protocol that's missing, which we
// don't need here since appId/title/activated all ride the Wayland list).
Column {
    id: root
    spacing: Theme.gap

    Repeater {
        model: ToplevelManager.toplevels

        delegate: Rectangle {
            id: cell
            required property var modelData
            readonly property bool focusedWin: modelData.activated
            readonly property var appEntry: modelData.appId
                ? DesktopEntries.heuristicLookup(modelData.appId) : null
            readonly property string iconName: appEntry && appEntry.icon
                ? appEntry.icon : (modelData.appId || "")

            width: Theme.wsCell
            height: Theme.wsCell
            radius: 0
            color: focusedWin ? Theme.bgAlt : "transparent"
            border.width: focusedWin ? 2 : 1
            border.color: focusedWin ? Theme.accent : Theme.dim

            IconImage {
                anchors.centerIn: parent
                visible: cell.iconName !== ""
                implicitSize: Theme.wsCell - 12
                source: Quickshell.iconPath(cell.iconName, "application-x-executable")
            }
            // fallback: first letter of the app id in the pixel font
            PixelText {
                anchors.centerIn: parent
                visible: cell.iconName === ""
                text: (cell.modelData.appId || cell.modelData.title || "?").charAt(0)
                color: Theme.dim
            }

            MouseArea {
                id: cellMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: cell.modelData.activate()
            }

            Tooltip {
                target: cell
                visible: cellMouse.containsMouse
                text: (cell.modelData.title || cell.modelData.appId || "?")
            }
        }
    }
}
