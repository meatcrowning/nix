import QtQuick
import Quickshell

// Right-click context menu for a Taskbar cell. Pops out to the LEFT of
// `target` (the bar hugs the right screen edge, same as Tooltip) and offers a
// graceful Close and a hard Force Quit for the window's process.
//
// Anchoring mirrors Tooltip.qml: recompute the mapping on every open (a
// Repeater cell laid out later keeps its birth y=0 in a plain binding), and
// take the window handle straight off target.QsWindow so the Taskbar doesn't
// need a hostWindow plumbed in.
//
// No compositor focus-grab is used here (this config never imports
// Quickshell.Hyprland), so dismissal is hover-driven: the menu closes shortly
// after the pointer leaves it, and auto-dismisses if it's opened but never
// entered.
PopupWindow {
    id: menu

    property Item target
    property var toplevel   // the Wayland Toplevel this menu acts on

    readonly property bool ready: target && target.QsWindow && target.QsWindow.window

    visible: false
    color: "transparent"
    implicitWidth: box.implicitWidth
    implicitHeight: box.implicitHeight

    property real anchorX: 0
    property real anchorY: 0
    function reposition() {
        if (!ready)
            return;
        const p = menu.target.mapToItem(null, 0, menu.target.height / 2);
        anchorX = p.x - 8;
        anchorY = p.y;
    }

    function open() {
        reposition();
        visible = true;
        graceTimer.restart();
    }
    function close() {
        visible = false;
    }

    anchor {
        window: menu.target ? menu.target.QsWindow.window : null
        rect {
            x: menu.anchorX
            y: menu.anchorY
            width: 1
            height: 1
        }
        edges: Edges.Left
        gravity: Edges.Left
    }

    // Close a beat after the pointer leaves the menu...
    Timer {
        id: leaveTimer
        interval: 400
        onTriggered: if (!menuHover.hovered) menu.close()
    }
    // ...and don't linger forever if it's opened but never entered.
    Timer {
        id: graceTimer
        interval: 2500
        onTriggered: if (!menuHover.hovered) menu.close()
    }

    Rectangle {
        id: box
        anchors.fill: parent
        implicitWidth: Math.max(closeRow.implicitWidth, killRow.implicitWidth)
        implicitHeight: closeRow.implicitHeight + killRow.implicitHeight
        color: Theme.bgAlt
        border.color: Theme.border
        border.width: 1
        radius: 3

        HoverHandler {
            id: menuHover
            onHoveredChanged: {
                if (hovered)
                    leaveTimer.stop();
                else
                    leaveTimer.restart();
            }
        }

        Column {
            anchors.fill: parent

            component MenuRow: Rectangle {
                property string label: ""
                property color labelColor: Theme.text
                signal activated()
                width: box.width
                implicitWidth: rowText.implicitWidth + 24
                implicitHeight: rowText.implicitHeight + 12
                color: rowMouse.containsMouse ? Theme.bg : "transparent"
                PixelText {
                    id: rowText
                    anchors.left: parent.left
                    anchors.leftMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    text: parent.label
                    textFormat: Text.PlainText
                    color: parent.labelColor
                }
                MouseArea {
                    id: rowMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: parent.activated()
                }
            }

            MenuRow {
                id: closeRow
                label: "Close"
                onActivated: {
                    if (menu.toplevel)
                        menu.toplevel.close();
                    menu.close();
                }
            }
            MenuRow {
                id: killRow
                label: "Force Quit"
                labelColor: Theme.accent
                onActivated: {
                    if (menu.toplevel)
                        Quickshell.execDetached(["sh",
                            Qt.resolvedUrl("scripts/force-quit.sh").toString().replace("file://", ""),
                            menu.toplevel.appId || "",
                            menu.toplevel.title || ""]);
                    menu.close();
                }
            }
        }
    }
}
