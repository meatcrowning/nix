import QtQuick
import "../../qmlcommon"

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
        font.hintingPreference: Font.PreferFullHinting
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

    // A Spin is a DISCRETE STEPPER, not a scroll surface, so the wheel goes
    // through the desktop's notch accumulator rather than a locally re-derived
    // set of constants (DESIGN.md §9.2, §19). One classic detent is exactly one
    // `step` as it always was; a touchpad's sub-notch remainder is carried, and
    // maxSteps caps a burst — the old hand-rolled `while` loop had no ceiling,
    // so a compositor momentum coast over a Spin could walk it across its whole
    // range on one flick.
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        WheelNotch { id: notch }
        onWheel: function (w) {
            var n = notch.steps(w)
            if (n !== 0)
                spin.commit(spin.value + n * spin.step)
            w.accepted = true
        }
    }
}
