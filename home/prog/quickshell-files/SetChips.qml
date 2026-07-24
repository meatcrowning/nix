import QtQuick

// A multi-select as a wrap of toggle chips (used for "which widgets show at
// login"). `options` is the full set of values; `selected` is the chosen subset
// (an array); toggling a chip emits changed(newArray). Order of the emitted
// array follows `options`, so the result is stable regardless of click order.
Flow {
    id: root
    property var options: []          // array of values
    property var labels: ({})         // optional { value: "display" }
    property var selected: []
    signal changed(var values)

    width: parent ? parent.width : 400
    spacing: 6

    function _has(v) { return (selected || []).indexOf(v) >= 0; }
    function _toggle(v) {
        const set = (selected || []).slice();
        const i = set.indexOf(v);
        if (i >= 0) set.splice(i, 1); else set.push(v);
        // re-order by `options` for a stable, readable array. Controlled: emit
        // only; `selected` stays bound to the store.
        changed(options.filter(o => set.indexOf(o) >= 0));
    }

    Repeater {
        model: root.options
        Rectangle {
            required property var modelData
            readonly property bool on: root._has(modelData)
            height: 22
            width: chipT.implicitWidth + 18
            color: on ? Theme.bgAlt : "transparent"
            border.width: 1
            border.color: (on || chipMa.containsMouse) ? Theme.accent : Theme.border
            PixelText {
                id: chipT
                anchors.centerIn: parent
                text: (root.labels && root.labels[parent.modelData] !== undefined) ? root.labels[parent.modelData] : parent.modelData
                color: parent.on ? Theme.accent : Theme.text
            }
            MouseArea {
                id: chipMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root._toggle(parent.modelData)
            }
        }
    }
}
