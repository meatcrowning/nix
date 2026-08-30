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
    radius: Theme.rounding
    border.color: editing ? Theme.accent : Theme.border
    border.width: Theme.ctrlBorder

    function clamp(v) { return Math.max(from, Math.min(to, v)) }
    function fmt(v) { return decimals > 0 ? v.toFixed(decimals) : String(Math.round(v)) }
    // NEVER assign `value` here. It is bound to the model (`root.gen.steps` and
    // friends), and writing a bound property in QML DESTROYS the binding — so
    // the first edit of a box permanently disconnected it, and every later
    // model change (a family's defaults landing on model select, a reused
    // image's parameters) silently stopped reaching it. Report the edit and let
    // the owner write it back; the text is set here only so the box shows the
    // CLAMPED number immediately rather than what was typed.
    function commit(v) {
        var c = clamp(v)
        if (c !== value) edited(c)
        input.text = fmt(c)
    }

    // The padding strips either side of the text used to be dead: a 92px box
    // whose left 5px did nothing when clicked. This sits under the input and
    // catches only what the input does not — clicking anywhere in the box now
    // starts editing, with the caret at the end nearest the click.
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        cursorShape: Qt.IBeamCursor
        onPressed: function (m) {
            input.forceActiveFocus()
            input.cursorPosition = m.x < spin.width / 2 ? 0 : input.length
        }
    }

    TextInput {
        id: input
        anchors.fill: parent
        anchors.leftMargin: 5
        anchors.rightMargin: 5
        verticalAlignment: TextInput.AlignVCenter
        color: Theme.text
        font: Theme.editorFont   // whole QFont: NoAntialias (docs/DESIGN.md 2.2)
        font.letterSpacing: Theme.fontLetterSpacing(Screen.devicePixelRatio)
        renderType: Text.NativeRendering
        selectByMouse: true
        selectionColor: Theme.accent
        text: spin.fmt(spin.value)
        onEditingFinished: spin.commit(parseFloat(text) || 0)
        Keys.onUpPressed: spin.commit(spin.value + spin.step)
        Keys.onDownPressed: spin.commit(spin.value - spin.step)
        // Escape leaves the box, restoring what the model says rather than
        // keeping a half-typed number on screen.
        Keys.onEscapePressed: function (e) {
            input.text = spin.fmt(spin.value)
            root.releaseFocus()
            e.accepted = true
        }
    }

    // Value only follows the model while the box is not being typed into.
    onValueChanged: if (!input.activeFocus) input.text = fmt(value)

    // A Spin is a DISCRETE STEPPER, not a scroll surface, so the wheel goes
    // through the desktop's notch accumulator rather than a locally re-derived
    // set of constants (docs/DESIGN.md §9.2, §19). One classic detent is exactly one
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
