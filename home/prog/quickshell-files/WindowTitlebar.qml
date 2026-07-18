import QtQuick
import Quickshell
import Quickshell.Wayland

// Vertical titlebar for one window. modelData is the window ADDRESS (a
// stable string — see WindowTracker.qml for why identity and geometry are
// split); everything positional comes from WindowTracker.geometry so a
// moving window slides this surface around instead of recreating it.
// Top to bottom: close, maximize (fill-workspace-area toggle, not
// fullscreen), then the title rotated vertical.
PanelWindow {
    id: root
    required property var modelData

    readonly property var geo: WindowTracker.geometry[modelData] ||
        ({ x: 0, y: 0, width: 0, height: 0, title: "" })

    // Single-monitor box (see CLAUDE.md) — same assumption
    // WindowTracker._monitorSize() makes.
    screen: Quickshell.screens[0]

    // Hyprland draws the 2px window border OUTSIDE at/size, so overshoot by
    // windowBorderWidth top and bottom to sit flush with the window's frame,
    // and let our own left border paint exactly over the window's right
    // border. The left margin is clamped at the panel's edge: dragging a
    // window far right slides the titlebar over the window's own right edge
    // rather than under (or into) the bar — the window itself is never
    // touched (the old resize-the-window reservation is gone).
    anchors { top: true; left: true }
    margins.top: geo.y - Theme.windowBorderWidth
    margins.left: Math.min(geo.x + geo.width,
        root.screen.width - Theme.barWidth - WindowTracker.titlebarWidth)
    implicitWidth: WindowTracker.titlebarWidth
    implicitHeight: geo.height + Theme.windowBorderWidth * 2
    exclusiveZone: -1
    color: "transparent"

    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.namespace: "qs-window-titlebar"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    readonly property bool maximized: !!WindowTracker.maximizedState[modelData]

    Rectangle {
        anchors.fill: parent
        color: Theme.bg
        border.width: Theme.windowBorderWidth
        border.color: Theme.windowBorder
    }

    Column {
        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter }
        anchors.topMargin: 2
        spacing: 2

        // ---- close ----
        Rectangle {
            id: closeBtn
            width: Theme.wsCell
            height: Theme.wsCell
            color: closeMouse.containsMouse ? Theme.bgAlt : "transparent"
            border.width: closeMouse.containsMouse ? 2 : 1
            border.color: closeMouse.containsMouse ? Theme.crit : Theme.border

            PixelText {
                anchors.centerIn: parent
                text: "x"
                color: closeMouse.containsMouse ? Theme.crit : Theme.textDim
            }

            MouseArea {
                id: closeMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: WindowTracker.closeWindow(root.modelData)
            }
        }

        // ---- maximize ----
        Rectangle {
            id: maxBtn
            width: Theme.wsCell
            height: Theme.wsCell
            color: root.maximized ? Theme.bgAlt : (maxMouse.containsMouse ? Theme.bgAlt : "transparent")
            border.width: (root.maximized || maxMouse.containsMouse) ? 2 : 1
            border.color: (root.maximized || maxMouse.containsMouse) ? Theme.accent : Theme.border

            Rectangle {
                anchors.centerIn: parent
                width: Theme.wsCell - 16
                height: width
                color: "transparent"
                border.width: 1
                border.color: root.maximized ? Theme.accent : Theme.textDim
            }

            MouseArea {
                id: maxMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: WindowTracker.toggleMaximize(root.modelData)
            }
        }
    }

    // ---- vertical title, below the buttons, filling the rest ----
    Item {
        id: titleArea
        anchors.fill: parent
        anchors.topMargin: (Theme.wsCell + 2) * 2 + 4

        Text {
            id: titleText
            text: root.geo.title
            font.family: Theme.font
            font.pixelSize: Theme.fontSize
            color: Theme.textDim
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignLeft
            // Pre-rotation: width is the available vertical run (what gets
            // elided against); height is the natural single-line text
            // height. Rotating -90 about the top-left corner then swings
            // the item to x in [0, implicitHeight], y in [-width, 0] — the
            // "y: width" shift below brings that back to [0, width], i.e.
            // back inside titleArea. Net effect: title reads bottom-to-top.
            width: titleArea.height
            rotation: -90
            transformOrigin: Item.TopLeft
            x: (WindowTracker.titlebarWidth - implicitHeight) / 2
            y: width
        }
    }
}
