import QtQuick
import Quickshell
import Quickshell.Widgets

// ONE running-program cell: app icon, focus treatment, click-to-focus /
// click-to-minimize, right-click menu, hover tooltip.
//
// Extracted from Taskbar.qml so the same cell can be laid out two ways without
// the behaviour existing twice: Taskbar.qml stacks these in a Column down the
// classic bar, and DockHeader.qml flows them across the dock panel's top,
// wrapping to a second row as they overflow.
Rectangle {
    id: cell
    required property var modelData

    readonly property bool focusedWin: modelData.activated
    // DesktopEntries scans lazily/asynchronously on first access, so at panel
    // startup (windows already open) heuristicLookup can return null before the
    // scan populates. A plain function-call binding would latch that null
    // forever (heuristicLookup registers no dependency on the model), leaving
    // apps whose window-class != icon-name stuck on the generic fallback. Touch
    // .applications.values so this binding re-runs once the scan finishes and
    // the real entry appears.
    readonly property var appEntry: {
        DesktopEntries.applications.values;
        return modelData.appId
            ? DesktopEntries.heuristicLookup(modelData.appId) : null;
    }
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
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        // Left-click the ACTIVE program's icon to minimize it (hyprvtb slides it
        // off-screen); left-click any other icon to focus it, which also slides
        // a minimized window back in. The minimize-on-click is gated on
        // taskbarClickMinimizes — when off, clicking the focused icon is a
        // no-op. Right-click opens the Close / Force Quit menu.
        onClicked: (mouse) => {
            if (mouse.button === Qt.RightButton) {
                cellMenu.open();
                return;
            }
            if (cell.modelData.activated) {
                if (SettingsStore.d.taskbarClickMinimizes)
                    Quickshell.execDetached(["hyprctl", "eval", "hl.plugin.hyprvtb.minimize_active()"]);
            } else {
                cell.modelData.activate();
            }
        }
    }

    Tooltip {
        target: cell
        visible: cellMouse.containsMouse && !cellMenu.visible
        text: (cell.modelData.title || cell.modelData.appId || "?")
    }

    TaskMenu {
        id: cellMenu
        target: cell
        toplevel: cell.modelData
    }
}
