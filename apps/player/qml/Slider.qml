import QtQuick

// A minimal themed horizontal slider — a track, a filled portion, and a
// draggable handle. Copied from surfer's Slider so both apps' pseudo-settings
// drawers feel the same. Controlled, not stateful: it never stores its own
// value. `value` is a binding the parent points at the source of truth, and
// drags only EMIT `moved(v)`; the parent writes the value back, which flows in
// through the `value` binding. That keeps the handle and the real setting in
// lock-step and avoids the binding-break a self-owned `value` would cause.
Item {
    id: root
    property real from: 0
    property real to: 10
    property real value: 0
    property real step: 1
    // The fill and the handle's edge are accent foregrounds and fade with the
    // window (docs/DESIGN.md §3.1.1); the `Theme.border` track and the
    // `Theme.bg` handle body do not.
    property color fgAccent: Theme.accent
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
        color: root.fgAccent
    }
    Rectangle {
        id: handle
        width: 8
        height: 14
        y: (parent.height - height) / 2
        x: root.frac * (root.width - width)
        color: Theme.bg
        border.color: root.fgAccent
        border.width: 1
    }
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        function pick(px) {
            if (root.width <= handle.width)
                return;
            var f = Math.max(0, Math.min(1, (px - handle.width / 2) / (root.width - handle.width)));
            var v = root.from + f * (root.to - root.from);
            v = Math.round(v / root.step) * root.step;
            root.moved(Math.max(root.from, Math.min(root.to, v)));
        }
        onPressed: function(m) { pick(m.x); }
        onPositionChanged: function(m) { if (pressed) pick(m.x); }
    }
}
