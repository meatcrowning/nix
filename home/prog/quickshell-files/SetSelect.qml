import QtQuick

// A compact enum picker. The options list is short (2-4 values everywhere it's
// used), so instead of an overlay dropdown it cycles in place: click / right-
// click (or the ‹ › ends) step through `options`. `value` is two-way and
// changed(v) fires on step. `labels` optionally maps a value to a nicer display
// string (e.g. an internal key -> a human label).
Rectangle {
    id: root
    property var options: []          // array of values
    property var labels: ({})         // optional { value: "display" }
    property string value: ""
    signal changed(string value)

    function _display(v) { return (labels && labels[v] !== undefined) ? labels[v] : v; }
    function _idx() { const i = options.indexOf(value); return i < 0 ? 0 : i; }
    function step(dir) {
        if (!options.length) return;
        const n = ((_idx() + dir) % options.length + options.length) % options.length;
        // Controlled: emit only; value stays bound to the store.
        changed(options[n]);
    }

    width: Math.max(96, label.implicitWidth + 44)
    height: 22
    color: ma.containsMouse ? Theme.bgAlt : "transparent"
    border.width: 1
    border.color: ma.containsMouse ? Theme.accent : Theme.border

    PixelText {
        anchors { left: parent.left; leftMargin: 6; verticalCenter: parent.verticalCenter }
        text: "‹"
        color: Theme.textDim
    }
    PixelText {
        id: label
        anchors.centerIn: parent
        text: root._display(root.value)
        color: Theme.text
    }
    PixelText {
        anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
        text: "›"
        color: Theme.textDim
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onClicked: (m) => root.step(m.button === Qt.RightButton ? -1 : 1)
    }
}
