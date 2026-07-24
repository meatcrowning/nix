import QtQuick

// A single-line text/number input themed to the panel. Controlled: bind `value`
// to the store; the field mirrors it while unfocused (so revert/restore refresh
// it), and commits (committed(text) fires) on Enter or focus-out — never on
// every keystroke, so persistence isn't spammed mid-typing. `numeric` limits
// input to a number; `fieldWidth` sizes it.
Rectangle {
    id: root
    property string value: ""
    property int fieldWidth: 180
    property bool numeric: false
    property string placeholder: ""
    signal committed(string text)

    // pull external changes in only while the user isn't editing
    onValueChanged: if (!field.activeFocus && field.text !== value) field.text = value;

    width: fieldWidth
    height: 24
    color: Theme.bgAlt
    border.width: 1
    border.color: field.activeFocus ? Theme.accent : (ma.containsMouse ? Theme.dim : Theme.border)

    TextInput {
        id: field
        anchors { fill: parent; leftMargin: 6; rightMargin: 6 }
        verticalAlignment: TextInput.AlignVCenter
        clip: true
        color: Theme.text
        font.family: Theme.font
        font.pixelSize: Theme.fontSize
        renderType: Text.NativeRendering
        selectByMouse: true
        selectionColor: Theme.highlight
        inputMethodHints: root.numeric ? Qt.ImhFormattedNumbersOnly : Qt.ImhNone
        Component.onCompleted: text = root.value
        onEditingFinished: root.committed(text)
        // re-sync to the source on cancel
        Keys.onEscapePressed: { text = root.value; focus = false; }
    }

    PixelText {
        anchors { fill: field }
        verticalAlignment: Text.AlignVCenter
        visible: field.text.length === 0 && !field.activeFocus
        text: root.placeholder
        color: Theme.textDim
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
        cursorShape: Qt.IBeamCursor
    }
}
