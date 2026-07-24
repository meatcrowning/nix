import QtQuick

// A colour picker as a swatch + hex field. `value` is a "#rrggbb" string, two-
// way; changed(hex) fires when a valid hex is committed. Clicking the swatch
// re-commits (handy after typing). Invalid text just doesn't apply.
Row {
    id: root
    property string value: "#000000"
    signal changed(string hex)

    spacing: 8

    function _valid(s) { return /^#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$/.test((s || "").trim()); }

    Rectangle {
        width: 22
        height: 22
        anchors.verticalCenter: parent.verticalCenter
        color: root._valid(root.value) ? root.value : Theme.bgAlt
        border.width: 1
        border.color: sw.containsMouse ? Theme.accent : Theme.border
        MouseArea {
            id: sw
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
        }
    }

    SetTextField {
        id: field
        anchors.verticalCenter: parent.verticalCenter
        fieldWidth: 90
        value: root.value
        placeholder: "#rrggbb"
        // Controlled: emit only; `value` stays bound to the store.
        onCommitted: (t) => { if (root._valid(t)) root.changed(t.trim()); }
    }
}
