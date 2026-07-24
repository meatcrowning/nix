import QtQuick

// A drag/click numeric slider with a live value readout. Works in integer or
// real steps; `value` is two-way and moved(v) fires on every change so the
// caller can persist. Click anywhere on the track to jump; drag the fill.
Row {
    id: root
    property real value: 0
    property real from: 0
    property real to: 100
    property real step: 1
    property string unit: ""
    property int decimals: (step < 1) ? 1 : 0
    signal moved(real value)

    spacing: 8

    function _clamp(v) {
        const stepped = root.from + Math.round((v - root.from) / root.step) * root.step;
        return Math.max(root.from, Math.min(root.to, stepped));
    }
    function _apply(px) {
        const frac = Math.max(0, Math.min(1, px / track.width));
        const v = _clamp(root.from + frac * (root.to - root.from));
        // Controlled: emit only. The caller writes the store synchronously in
        // moved(), and value (bound to the store) updates this frame, so the
        // fill tracks the drag while revert/restore still refresh it.
        if (v !== root.value) root.moved(v);
    }

    Rectangle {
        id: track
        width: 160
        height: 8
        anchors.verticalCenter: parent.verticalCenter
        color: Theme.bgAlt
        border.width: 1
        border.color: ma.containsMouse ? Theme.accent : Theme.border

        // filled portion
        Rectangle {
            height: parent.height
            width: Math.round((root.to > root.from ? (root.value - root.from) / (root.to - root.from) : 0) * parent.width)
            color: Theme.accent
        }
        // handle
        Rectangle {
            width: 4
            height: parent.height + 6
            anchors.verticalCenter: parent.verticalCenter
            x: Math.min(parent.width - width, Math.round((root.to > root.from ? (root.value - root.from) / (root.to - root.from) : 0) * parent.width))
            color: Theme.text
        }

        MouseArea {
            id: ma
            anchors { fill: parent; margins: -4 }
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onPressed: (m) => root._apply(m.x)
            onPositionChanged: (m) => { if (pressed) root._apply(m.x); }
        }
    }

    PixelText {
        anchors.verticalCenter: parent.verticalCenter
        width: 52
        horizontalAlignment: Text.AlignRight
        text: root.value.toFixed(root.decimals) + (root.unit ? " " + root.unit : "")
        color: Theme.text
    }
}
