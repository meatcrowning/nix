import QtQuick

// A minimal themed horizontal slider — a track, a filled portion, and a draggable
// handle. Controlled, not stateful: it never stores its own value. `value` is a
// binding the parent points at the source of truth (e.g. DarkMode.brightness),
// and drags only EMIT `moved(v)`; the parent writes the value back, which flows
// in through the `value` binding. That keeps the handle and the real setting in
// lock-step and avoids the binding-break a self-owned `value` would cause.
Item {
    id: root
    property real from: 50
    property real to: 150
    property real value: 100
    property int step: 5
    signal moved(real v)

    implicitWidth: 150
    implicitHeight: 16

    readonly property real frac: (to > from) ? Math.max(0, Math.min(1, (value - from) / (to - from))) : 0

    Rectangle {   // track
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
        height: 2
        color: Theme.border
    }
    Rectangle {   // filled portion, up to the handle
        anchors.verticalCenter: parent.verticalCenter
        x: 0
        width: handle.x + handle.width / 2
        height: 2
        color: Theme.accent
    }
    Rectangle {
        id: handle
        width: 8
        height: 14
        y: (parent.height - height) / 2
        x: root.frac * (root.width - width)
        color: Theme.bg
        border.color: Theme.accent
        border.width: 1
    }
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        function pick(px) {
            var f = Math.max(0, Math.min(1, (px - handle.width / 2) / (root.width - handle.width)));
            var v = root.from + f * (root.to - root.from);
            v = Math.round(v / root.step) * root.step;
            root.moved(Math.max(root.from, Math.min(root.to, v)));
        }
        onPressed: (m) => pick(m.x)
        onPositionChanged: (m) => { if (pressed) pick(m.x); }
    }
}
