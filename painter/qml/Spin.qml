import QtQuick

// Numeric entry with drag-to-scrub and wheel support.  Kept deliberately plain:
// a pixel-font text box with a thin frame, matching the rest of the desktop.
Rectangle {
    id: spin
    property real value: 0
    property real from: 0
    property real to: 1000000
    property real step: 1
    property int decimals: 0
    property bool editing: input.activeFocus

    signal edited(real value)

    width: 92
    height: 20
    color: Theme.bg
    border.color: editing ? Theme.accent : Theme.border
    border.width: 1
    radius: 1

    function clamp(v) { return Math.max(from, Math.min(to, v)) }
    function fmt(v) { return decimals > 0 ? v.toFixed(decimals) : String(Math.round(v)) }
    function commit(v) {
        var c = clamp(v)
        if (c !== value) { value = c; edited(c) }
        input.text = fmt(value)
    }

    TextInput {
        id: input
        anchors.fill: parent
        anchors.leftMargin: 5
        anchors.rightMargin: 5
        verticalAlignment: TextInput.AlignVCenter
        color: Theme.text
        font.family: Theme.font
        font.pixelSize: Theme.fontSize
        font.hintingPreference: Font.PreferNoHinting
        renderType: Text.NativeRendering
        selectByMouse: true
        selectionColor: Theme.accent
        text: spin.fmt(spin.value)
        onEditingFinished: spin.commit(parseFloat(text) || 0)
        Keys.onUpPressed: spin.commit(spin.value + spin.step)
        Keys.onDownPressed: spin.commit(spin.value - spin.step)
    }

    // Value only follows the model while the box is not being typed into.
    onValueChanged: if (!input.activeFocus) input.text = fmt(value)

    // The wheel steps by ACCUMULATED delta, not once per event.  A trackpad
    // sends a burst of small pixelDelta events per flick, and one step each ran
    // denoise 40% of its range (and the seed off by dozens) on a single gesture.
    // 120 units of angleDelta / 40 px of pixelDelta = one step, so a classic
    // wheel detent still moves the value by exactly `step` as it always did;
    // the fractional remainder is carried, never dropped.
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        property real wheelAcc: 0
        onWheel: function (w) {
            // angleDelta is 12x the true pixel delta, so a sub-pixel touchpad
            // event (pixelDelta rounds to 0) must divide by 12*40, not 120 —
            // otherwise slow scrolling steps 4x faster than normal scrolling.
            // >= 120 means a real wheel detent: one step, as it always was.
            var ad = w.angleDelta.y
            wheelAcc += w.pixelDelta.y !== 0 ? w.pixelDelta.y / 40
                      : Math.abs(ad) >= 120  ? ad / 120
                      :                        ad / 480
            while (Math.abs(wheelAcc) >= 1) {
                if (wheelAcc > 0) { spin.commit(spin.value + spin.step); wheelAcc -= 1 }
                else              { spin.commit(spin.value - spin.step); wheelAcc += 1 }
            }
            w.accepted = true
        }
    }
}
