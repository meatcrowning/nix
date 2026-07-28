import QtQuick
import Quickshell

// Right-click context menu for a row of the task manager's process table.
//
// It is a sibling of TaskMenu.qml (the taskbar cell's menu) and deliberately
// mirrors it: a PopupWindow opening to the LEFT of the pointed-at row, since
// the bar hugs the right screen edge; no compositor focus grab (this config
// never imports Quickshell.Hyprland), so dismissal is hover-driven — a beat
// after the pointer leaves, and a grace timeout if it is opened but never
// entered.
//
// ONE INSTANCE PER TABLE, not one per row, and it captures the row's values on
// open. The list re-sorts every 2s and `reuseItems` recycles delegates, so a
// menu owned by a delegate would be destroyed or silently re-pointed at a
// different process while it was on screen. What it acts on is the pid it was
// opened with, which is the same rule the [x] button follows.
//
// EVERY ACTION IS A FIRE-AND-FORGET execDetached with no exit code (see
// Procs.qml), so an action the kernel would refuse must not be OFFERED: rows
// the sampler reports as somebody else's (`mine` false) get the read-only
// entries only, plus a line saying why. Silently doing nothing is the failure
// mode this menu exists to avoid, not one it may reintroduce.
PopupWindow {
    id: menu

    // The stable item the popup anchors against — the task manager content
    // root, NOT the row (which may be recycled out from under an open menu).
    property Item host

    // Captured at open. Nothing here binds to the live model.
    property string pid: ""
    property string pname: ""
    property string pstate: "?"
    property int pnice: 0
    property bool mine: true

    readonly property bool stopped: pstate === "T"
    readonly property bool ready: host && host.QsWindow && host.QsWindow.window

    visible: false
    color: "transparent"
    implicitWidth: box.implicitWidth
    implicitHeight: box.implicitHeight

    property real anchorX: 0
    property real anchorY: 0

    // `row` is the delegate the click landed in; it is used ONCE, here, to
    // place the popup, and never held.
    function openFor(row, p) {
        if (!ready || !p)
            return;
        menu.pid = String(p.pid);
        menu.pname = p.name || "?";
        menu.pstate = p.state || "?";
        menu.pnice = p.nice || 0;
        menu.mine = p.mine !== false;
        // Scene coordinates, like Tooltip/TaskMenu: mapToItem(null) maps to the
        // scene root, which is what anchor.rect is relative to. Recomputed on
        // every open — a delegate laid out later keeps its birth y in a plain
        // binding.
        const pt = row.mapToItem(null, 0, row.height / 2);
        anchorX = pt.x - 8;
        anchorY = pt.y;
        visible = true;
        graceTimer.restart();
    }
    function close() { visible = false; }

    anchor {
        window: menu.ready ? menu.host.QsWindow.window : null
        rect {
            x: menu.anchorX
            y: menu.anchorY
            width: 1
            height: 1
        }
        edges: Edges.Left
        gravity: Edges.Left
    }

    Timer {
        id: leaveTimer
        interval: 400
        onTriggered: if (!menuHover.hovered) menu.close()
    }
    Timer {
        id: graceTimer
        interval: 2500
        onTriggered: if (!menuHover.hovered) menu.close()
    }

    Rectangle {
        id: box
        anchors.fill: parent
        implicitWidth: col.implicitWidth
        implicitHeight: col.implicitHeight
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

        // A clickable entry. Invisible rows are skipped by the Column and drop
        // out of its implicit size, so the menu is exactly as tall as the
        // actions this particular process actually has.
        component MenuRow: Rectangle {
            property string label: ""
            property color labelColor: Theme.text
            signal activated()
            width: box.width
            implicitWidth: rowText.implicitWidth + 24
            implicitHeight: rowText.implicitHeight
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

        // A non-interactive line: the header, and the "not yours" note.
        component MenuNote: Item {
            property string label: ""
            property color labelColor: Theme.textDim
            width: box.width
            implicitWidth: noteText.implicitWidth + 24
            implicitHeight: noteText.implicitHeight
            PixelText {
                id: noteText
                anchors.left: parent.left
                anchors.leftMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: parent.label
                textFormat: Text.PlainText
                color: parent.labelColor
                elide: Text.ElideRight
                width: Math.min(implicitWidth, box.width - 20)
            }
        }

        component MenuSep: Item {
            width: box.width
            implicitWidth: 1
            implicitHeight: 5
            Rectangle {
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                height: 1
                color: Theme.border
            }
        }

        Column {
            id: col
            anchors.fill: parent

            // Which process this is about. The table re-sorts under the
            // pointer, so a menu that did not name its target would be a
            // coin flip about what the next click ends.
            MenuNote {
                label: menu.pname + " (" + menu.pid + ")"
                labelColor: Theme.accent
            }
            MenuSep {}

            MenuRow {
                visible: menu.mine
                label: "End Task"
                onActivated: { Procs.kill(menu.pid, false); menu.close(); }
            }
            MenuRow {
                visible: menu.mine
                label: "Force Quit"
                labelColor: Theme.crit
                onActivated: { Procs.kill(menu.pid, true); menu.close(); }
            }
            MenuRow {
                visible: menu.mine && !menu.stopped
                label: "Suspend"
                onActivated: { Procs.signal(menu.pid, "STOP"); menu.close(); }
            }
            MenuRow {
                visible: menu.mine && menu.stopped
                label: "Resume"
                onActivated: { Procs.signal(menu.pid, "CONT"); menu.close(); }
            }
            // Niceness is one-way without privilege, so this is offered only
            // while there is room to go up, and never as a way back down.
            MenuRow {
                visible: menu.mine && menu.pnice < 19
                label: "Lower Priority"
                onActivated: { Procs.renice(menu.pid, Math.min(19, menu.pnice + 10)); menu.close(); }
            }
            MenuNote {
                visible: !menu.mine
                label: "not yours - signals refused"
                labelColor: Theme.warn
            }

            MenuSep { visible: menu.mine }

            MenuRow {
                label: "Filter by Name"
                onActivated: { Procs.setFilter(menu.pname); menu.close(); }
            }
            MenuRow {
                label: "Copy PID"
                onActivated: { Procs.copyText(menu.pid); menu.close(); }
            }
        }
    }
}
